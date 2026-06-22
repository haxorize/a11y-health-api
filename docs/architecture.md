# Architecture

How this service is put together and why it behaves the way it does. This is the
reading-first companion to the code: it explains the cross-cutting stories —
scoring, the scan-run lifecycle, pagination, the API contract, and how to operate
the thing — that no single file can tell on its own.

Two siblings to this document:

- **`DOMAIN.md`** — the glossary. Every **bold term** here (App, Scan Run, Page
  Health, Rollup, …) is defined there. Read it first if a word is unfamiliar.
- **`docs/adr/`** — the decision log. Where a choice below is non-obvious, it
  links the ADR that records *why*.

---

## 1. The layers

A request flows through four layers, each with one job. Nothing skips a layer.

```
HTTP request
   │
   ▼
endpoint   api/v1/endpoints/*.py   thin: parse input, call a service, serialize output
   │
   ▼
service    services/*.py           all business logic and database access
   │
   ▼
model      models/*.py             SQLAlchemy tables (the shape of the data)
   │
   ▼
PostgreSQL
```

**Endpoints** (`api/v1/endpoints/`) are deliberately thin. They declare the URL,
accept a request validated by a **schema**, hand off to a service, and convert the
result back into a response schema. A whole endpoint is usually three lines —
e.g. `create_app` in `api/v1/endpoints/apps.py`:

```python
@router.post("", status_code=201)
async def create_app(db: DbSession, data: AppCreate) -> AppRead:
    app = await app_service.create_app(db, data)
    return AppRead.model_validate(app)
```

`DbSession` (defined in `api/deps.py`) is how every endpoint gets a database
session — FastAPI injects it automatically. Endpoints never contain business
rules; if you find logic in an endpoint, it belongs in a service.

**Services** (`services/`) own everything that matters: queries, validation that
needs the database, and the domain operations (scoring, rollups, status
transitions). They take a session plus plain arguments and return ORM objects or
a `CursorPage` — never HTTP types. This is what makes them reusable: the CLI
(section 6) drives the same behavior over HTTP, and tests call services directly.

**Models** (`models/`) are SQLAlchemy table definitions — the columns, types, and
foreign keys. **Schemas** (`schemas/`) are Pydantic classes for request and
response bodies; they are *not* the database models, and keeping them separate is
what lets the stored shape and the wire shape evolve independently.

**`core/`** holds the cross-cutting machinery every layer leans on: `database.py`
(engine, session, base classes), `pagination.py` (section 4), and `exceptions.py`
(the domain error types).

### How the database session and transactions work

`core/database.py`'s `get_db()` opens one session per request and wraps it in a
transaction: **commit on success, roll back on any exception**. Services and
endpoints therefore never call `commit()` themselves — they just `flush()` when
they need a generated id mid-request. One request is one atomic unit of work.

A session is *not* safe to share across concurrent tasks — see
[ADR 0007](adr/0007-async-session-not-concurrency-safe.md). Tests rely on the
rollback behavior for isolation — [ADR 0011](adr/0011-transactional-rollback-test-isolation.md).

### How errors become HTTP status codes

Services raise **semantic** exceptions from `core/exceptions.py` —
`NotFoundError`, `DuplicateSlugError`, `InvalidStatusTransitionError`, and so on.
They do not know or care about HTTP. `main.py` owns the single mapping from each
exception type to a status code:

| Exception | Status |
| --- | --- |
| `NotFoundError` | 404 |
| `CircularReferenceError`, `DuplicateSlugError`, `HasDependentsError`, `InvalidStatusTransitionError`, `ScanRunCompletedError` | 409 |
| `InvalidCursorError` | 400 |
| Pydantic `ValidationError` (bad request body) | 422 |

So: to add a new failure mode, raise a domain exception in the service and
register its status in `main.py`. The endpoint stays untouched.

---

## 2. The scoring & rollup model

This is the heart of the system and the part worth reading slowly. The code lives
in `services/score_snapshot.py`. Terms: **Page Health**, **Score**, **Score
Snapshot**, **Rollup** — all in `DOMAIN.md`.

### Step 1 — each page gets a Page Health

A **Page Result**'s health is decided by the **worst Impact** among its
**Violation** findings. **Incompletes never count** — they are stored for manual
review but excluded from every score
([ADR 0006](adr/0006-incompletes-excluded-from-score.md)). The impact-to-health
map is intentionally lossy:

| Worst violation impact | Page Health |
| --- | --- |
| critical | Critical |
| serious | Serious |
| moderate | Fair |
| minor, or no violations | Good |

Page Health uses different words from Impact on purpose, so "the page is Fair" is
never confused with "an issue is moderate" —
[ADR 0005](adr/0005-page-health-distinct-from-impact.md).

### Step 2 — the app's Score is a weighted average of its pages

Each Page Health carries a weight: **Critical = 0, Serious = 0.4, Fair = 0.8,
Good = 1.0**. The **Score** is the mean of those weights across all pages:

```
score = (0·critical_pages + 0.4·serious_pages + 0.8·fair_pages + 1.0·good_pages) / total_pages
```

A perfect app scores 1.0; an all-critical app scores 0.0. The result is saved as
a **Score Snapshot** — a denormalized row holding the score plus summary metrics
(total violations, % pages with violations, etc.). An app snapshot's
`snapshot_at` is the **Scan Run's `scanned_at`** (when the scan happened), not
when it was uploaded.

### Step 3 — the score rolls up to Org Units and Brands

Once an app snapshot exists, the totals roll up to the owners. A **Score
Snapshot** belongs to exactly one of an App, an Org Unit, or a Brand — never more
than one ([ADR 0002](adr/0002-score-snapshot-mutex-owner.md)). There are two
rollup shapes:

- **Org Unit Rollup is hierarchical and cascades.** An org unit recomputes from
  its children's *latest* snapshots (child apps **and** child org units), then
  calls itself on its parent, walking to the root.
- **Brand Rollup is flat.** A brand aggregates the latest snapshots of all its
  apps in one shot, regardless of where those apps sit in the org tree. It does
  not cascade. [ADR 0004](adr/0004-org-unit-rollup-cascades-brand-rollup-flat.md).

A parent's `score` is the **unweighted arithmetic mean of its children's
scores** — every child counts equally, a 2-page app and a 2000-page app alike.
Note a subtlety captured in the code: the `pct_*` / `avg_*` metrics on a rollup
are recomputed from *summed totals*, so the headline score and those ratios can
legitimately diverge.

> **Why snapshots get pruned during a rollup.** Snapshots are append-only
> ([ADR 0015](adr/0015-score-snapshot-append-only.md)), so a rollup writes a new
> row rather than mutating one. The new row's `snapshot_at` is the newest among
> its children. Any existing owner snapshot dated *after* that — left behind by
> data that has since been deleted — is now orphaned (the numbers behind it are
> gone), so the rollup deletes those forward rows before inserting. If a node
> ends up with no children at all, its snapshots are deleted outright.

### What triggers a rollup

`services/scoring_orchestration.py` is the switchboard. Any event that changes an
app's latest snapshot fires the appropriate rollups:

| Event | What recomputes |
| --- | --- |
| Scan Run completed | app score, then its org-unit chain and its brand |
| Scan Run deleted | the app's org-unit chain and brand |
| App deleted | the (former) org-unit chain and brand |
| App reassigned to a new Org Unit | both old and new org-unit chains |
| Org Unit reparented | both old and new parent chains |

---

## 3. The scan-run lifecycle

A **Scan Run** is a small state machine (`services/scan_run.py`):

```
            add Page Results                 transition
   ┌───────────────────────────┐         (triggers scoring)
   │                           ▼                  │
[ PENDING ] ─────────────────────────────► [ COMPLETED ]   (terminal)
```

- A run is created **Pending**. Pages may be added only while Pending; posting a
  page to a Completed run raises `ScanRunCompletedError` → 409.
- The **only** legal transition is Pending → Completed
  (`_VALID_TRANSITIONS`). Anything else raises `InvalidStatusTransitionError` →
  409. Completed is terminal — there is no reopening.
- The Pending → Completed transition is what **triggers scoring**: it calls
  `on_scan_run_completed`, which computes the app score and runs both rollups
  (section 2).

This is why ingestion is always "create run → add pages → complete run," in that
order (section 6).

---

## 4. Pagination

Every list endpoint is **keyset (cursor) paginated** through one shared function,
`paginate()` in `core/pagination.py` —
[ADR 0017](adr/0017-keyset-pagination-deep-module.md). No list service hand-rolls
its own paging.

What a caller does: pass a filtered query plus the **keyset** (the columns that
order and tiebreak the results), and `paginate` handles the rest — applying the
cursor, ordering, fetching `limit + 1` rows to detect whether more exist, slicing,
and encoding the `next_cursor`. A **cursor** is just the keyset values of the last
row, base64-encoded; the client sends it back to get the next page. Paging is
**forward-only and ascending**, always tiebroken by `id`.

Two things to know if you touch it:

- Keyset columns must be **NOT NULL** (a NULL breaks the row-value comparison and
  silently drops rows). All current keysets are primary keys or NOT NULL columns.
- An optional `into` callback maps each result row into a response object. Most
  lists return ORM objects directly; `list_page_metrics` uses `into` to shape
  aggregate query rows into `PageMetricsRead`.

---

## 5. The OpenAPI contract pipeline

The API is the **source of truth** for the contract the UI consumes. The full
cross-repo flow is documented in the workspace `CLAUDE.md` ("Changing the
contract"); the API-side essentials:

- `make openapi` writes a deterministic `openapi.json`, committed alongside code
  so contract changes show up in PR diffs.
- Each endpoint's **operation id** is its **route function name**
  (`_operation_id` in `main.py`), and that name becomes the UI's generated method
  name. Consequently **two endpoint functions may not share a name across
  routers** — a collision corrupts `openapi.json` and breaks UI codegen. Keep
  route function names unique repo-wide.

---

## 6. Operating & debugging

### Getting scan data in: the CLI

`cli.py` (`uv run a11y …`) is a thin client that drives the *public API over
HTTP* — it has no direct database access, so anything it does, you could do with
`curl`. Two commands, chosen by app state:

- **`a11y ingest <dir>`** — upload one scan to an **existing** app. It reads the
  JSON files in the directory, resolves the app by the `name` field in the payload
  (the **Slug**), then runs the lifecycle: create Scan Run → POST each page →
  PATCH to Completed. If the app isn't registered it raises `AppNotFoundError`
  pointing you to `import`.
- **`a11y import <dir> --org-unit-id <id> --brand-id <id>`** — onboard an app
  from a directory of `YYYY-MM-DD/` subdirectories, creating the app if missing
  and uploading each date subdirectory as its own Scan Run.

The **Slug** is derived from the axe JSON `name` and is immutable
([ADR 0010](adr/0010-slug-derived-from-axe-name-immutable.md)). Common CLI
failures and what they mean:

| Error | Cause |
| --- | --- |
| `AppNotFoundError` | `ingest` against an app that was never imported |
| `NoDateDirsError` | `import` against a directory with no `YYYY-MM-DD/` subdirs |
| `NameResolutionError` | JSON files missing a `name`, or disagreeing on it |

### Tracing a request

Endpoint (`api/v1/endpoints/`) → service (`services/`) → model. A failing request
surfaces as a JSON `{"detail": …}` body; the status code tells you which layer
rejected it (404/409 = a domain exception from a service; 422 = the request body
failed schema validation before any service ran). Map the status back through the
table in section 1 to the exception, then grep for where that exception is raised.

### Inspecting the data

- Every **Page Result** keeps its full axe payload as **Raw JSON** (JSONB) for
  reprocessing and debugging — [ADR 0008](adr/0008-defer-jsonb-by-access-pattern.md)
  explains why it's loaded only on demand.
- Set `DEBUG=true` (see `config.py`) to echo every SQL statement the engine runs.
- `GET /api/v1/health` is the liveness check; Swagger UI is at `/docs`, ReDoc at
  `/redoc`.
