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
a `CursorPage` — never HTTP types, so tests can call them directly without
spinning up the web layer.

**Models** (`models/`) are SQLAlchemy table definitions — the columns, types, and
foreign keys. **Schemas** (`schemas/`) are Pydantic classes for request and
response bodies; they are *not* the database models, and keeping them separate is
what lets the stored shape and the wire shape evolve independently.

**`core/`** holds the cross-cutting machinery every layer leans on: `database.py`
(engine, session, base classes), `pagination.py` (see [Pagination](#4-pagination)),
`exceptions.py` (the domain error types), `error_contract.py` (the **Error
Contract** — how domain errors become HTTP responses and contract declarations),
and `existence.py` (the **Existence Guard** — see below).

### The Existence Guard and the two-tier call rule

Checking that a referenced entity exists before an operation proceeds is one
concept, owned by one deep module: `core/existence.py`. It has two entry
points — `get_by_pk(session, model, id)` and `get_by_query(session, model,
stmt, id)` — both returning the entity or raising `NotFoundError` with the
entity's label from the module's one closed label table. That table is the only
place entity label text lives (the services' other error modes read their
entity's name from it too), and the guard is the only module that raises
`NotFoundError` (a test pins both).

Callers follow a **two-tier call rule**:

- **Each entity's own service keeps its named accessors** (`get_app`,
  `get_app_by_slug`, `get_brand`, `get_org_unit`, `get_scan_run`,
  `get_finding`) delegating to the guard. Endpoints read through these
  accessors, never through the guard.
- **Every other module calls the guard directly** — `existence.get_by_pk(...)`
  with the model class. No service ever imports a sibling service just to ask
  "does it exist?" (or to fetch an entity it only reads); that import topology
  is what previously forced function-local imports to dodge cycles.

The guard lives in the service/domain layer — not in endpoint dependencies —
because services are entered from the CLI and scoring orchestration as well as
from transport; a transport-level check would silently unguard those paths and
violate the thin-endpoint rule. It concentrates the not-found mode into a
single raise site the same way `paginate()` concentrated keyset pagination
([ADR 0017](adr/0017-keyset-pagination-deep-module.md)). Rationale and
rejected alternatives:
[ADR 0024](adr/0024-existence-guard-core-module-two-tier-rule.md).

### How the database session and transactions work

`core/database.py`'s `get_db()` opens one session per request and wraps it in a
transaction: **commit on success, roll back on any exception**. Services and
endpoints therefore never call `commit()` themselves — they just `flush()` when
they need a generated id mid-request. One request is one atomic unit of work.

A session is *not* safe to share across concurrent tasks — see
[ADR 0007](adr/0007-async-session-not-concurrency-safe.md). Tests rely on the
rollback behavior for isolation — [ADR 0011](adr/0011-transactional-rollback-test-isolation.md).

### How errors become HTTP status codes

Services raise **semantic** exceptions — subclasses of `DomainError` from
`core/exceptions.py` (`NotFoundError`, `DuplicateSlugError`, and so on; the
pagination module contributes `InvalidCursorError`). They do not know or care
about HTTP. `core/error_contract.py` owns the **Error Contract**: one table
(`ERROR_MODES`) maps each domain error mode to its status and machine-readable
**Error Code**, and everything else derives from that table — the runtime
handler (registered once for `DomainError`), the shared `ErrorBody` response
shape (`{"code", "message"}`), and each operation's OpenAPI declaration
(`error_responses(...)` on the route decorator, which also embeds the declared
codes as `x-error-codes`).

| Mode (exception → code) | Status |
| --- | --- |
| `NotFoundError` → `not_found` | 404 |
| `CircularReferenceError` → `circular_reference`, `DuplicateSlugError` → `duplicate_slug`, `EmptyScanRunError` → `empty_scan_run`, `HasDependentsError` → `has_dependents`, `InvalidStatusTransitionError` → `invalid_status_transition`, `ScanRunCompletedError` → `scan_run_completed` | 409 |
| `InvalidCursorError` → `invalid_cursor`, `InvalidAxePayloadError` → `invalid_axe_payload` | 400 |
| Pydantic `ValidationError` (request failed FastAPI's own shape validation) | 422 |

The 400-vs-422 rule: **422 belongs to the framework** — it means the request
never matched the declared request schema, with FastAPI's standard error body.
A request that is well-formed but fails *domain* validation (a malformed
cursor, an axe payload that doesn't parse) returns **400 with a coded body**.
There is no app-level handler for `ValidationError`: an internal validation
failure escaping the domain is a bug and surfaces as a 500, never a disguised
client error. See
[ADR 0022](adr/0022-error-contract-single-table-400-vs-422.md).

So: to add a new failure mode, subclass `DomainError`, add its row to
`ERROR_MODES`, and list its code in `error_responses(...)` on the operations
that can produce it. An exhaustiveness test fails if a `DomainError` subclass
lacks a table entry, and the test suite's declaration-honesty shim (the ASGI
wrapper in `tests/_declaration_honesty.py`, applying
`error_contract.assert_declared_mode`) fails any test that observes an
undeclared error status or code. The endpoint logic stays untouched.

---

## 2. The scoring & rollup model

This is the heart of the system and the part worth reading slowly. The code lives
in `services/score_snapshot.py`. Terms: **Page Health**, **Score**, **Score
Snapshot**, **Rollup** — all in `DOMAIN.md`.

The *meaning* behind the scoring value sets — the health ordering (worst → best,
each health's rank derived from its position), the health weights, and the total
Impact → Page Health mapping — has one home: the **Scoring Vocabulary** module,
`services/_scoring_vocabulary.py`. The scoring engine imports it, and
`GET /scoring-vocabulary` serves the deployed server's copy so no client
hard-codes it ([ADR 0020](adr/0020-scoring-vocabulary-runtime-endpoint.md)). The
tables and weights quoted below are illustrations of that vocabulary, not a
second authority.

### Step 1 — each page gets a Page Health

A **Page Result**'s health is decided by the **worst Impact** among its
**Violation** findings. **Incompletes never count** — they are stored for manual
review but excluded from every score
([ADR 0006](adr/0006-incompletes-excluded-from-score.md)). The vocabulary's
Impact → Page Health mapping is intentionally lossy — and **total**: every
Impact maps explicitly, so there is no "unmapped means Good" default. A page
with no violations at all is Good; that empty case is the engine's, not the
mapping's.

| Worst violation impact | Page Health |
| --- | --- |
| critical | Critical |
| serious | Serious |
| moderate | Fair |
| minor | Good |

Page Health uses different words from Impact on purpose, so "the page is Fair" is
never confused with "an issue is moderate" —
[ADR 0005](adr/0005-page-health-distinct-from-impact.md).

### Step 2 — the app's Score is a weighted average of its pages

Each Page Health carries a weight in the vocabulary — currently **Critical = 0,
Serious = 0.4, Fair = 0.8, Good = 1.0**. The **Score** is the mean of those
weights across all pages:

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

"Latest" has exactly one definition — newest `snapshot_at`, ties broken by
`id`, per owner — owned by `services/_latest_snapshot.py` and shared by both
rollup shapes and the `GET /scores/latest` read endpoint
([ADR 0023](adr/0023-scores-latest-read-endpoint.md)), so what a dashboard shows
as "latest" can never disagree with what rollups aggregate.

A parent's `score` is the **unweighted arithmetic mean of its children's
scores** — every child counts equally, a 2-page app and a 2000-page app alike.
The count columns, by contrast, are *summed totals* — so a share or average a
consumer derives from a rollup's counts is page-weighted and can legitimately
diverge from the headline score.

> **Why snapshots get pruned during a rollup.** Snapshots are append-only
> ([ADR 0015](adr/0015-score-snapshot-append-only.md)), so a rollup writes a new
> row rather than mutating one. The new row's `snapshot_at` is the newest among
> its children. Any existing owner snapshot dated *after* that — left behind by
> data that has since been deleted — is now orphaned (the numbers behind it are
> gone), so the rollup deletes those forward rows before inserting. If a node
> ends up with no children at all, its snapshots are deleted outright.
>
> **One snapshot per distinct observation.** A rollup trigger is not itself an
> observation (#95): when the recomputed aggregate lands on the observation time
> the owner's latest snapshot already holds, identical values record nothing,
> and changed values replace the rows sharing that time (delete + insert, never
> update). Only a newer observation time appends — even when the values didn't
> move, so the latest snapshot never claims an observation whose source data has
> since been deleted.

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
- Completing requires **at least one Page Result** — an empty run raises
  `EmptyScanRunError` → 409, because its snapshot would score "no data" as 0.0
  and roll that up into every ancestor mean.
- The Pending → Completed transition is what **triggers scoring**: it calls
  `on_scan_run_completed`, which computes the app score and runs both rollups
  (see [The scoring & rollup model](#2-the-scoring--rollup-model)).

This is why ingestion is always "create run → add pages → complete run," in that
order (see [Operating & debugging](#6-operating--debugging)).

---

## 4. Pagination

Every **unbounded** list endpoint is **keyset (cursor) paginated** through one
shared function, `paginate()` in `core/pagination.py` —
[ADR 0017](adr/0017-keyset-pagination-deep-module.md). No list service hand-rolls
its own paging. Bounded reference collections — brand and org-unit listings and
the ancestors/descendants traversals — deliberately return bare arrays instead;
the boundary is the data's growth model, not its row count
([ADR 0025](adr/0025-bounded-reference-lists-stay-bare-arrays.md)).

What a caller does: pass a filtered query plus the **keyset** (the columns that
order and tiebreak the results), and `paginate` handles the rest — applying the
cursor, ordering, fetching `limit + 1` rows to detect whether more exist, slicing,
and encoding the `next_cursor`. A **cursor** is just the keyset values of the last
row, base64-encoded; the client sends it back to get the next page. Paging is
**forward-only**, tiebroken by `id` wherever the keyset isn't already unique.
Direction is ascending unless the operation says otherwise: most listings bake
their direction server-side (Scan Run history pages newest-first), and the three
score-history listings let the client choose via an `order` query param
(`asc`/`desc`, ascending by default).

`paginate` returns the internal `CursorPage` (ORM items + cursor); the endpoint turns
that into the public `Page` wire response with `Page.from_cursor_page(page, ItemRead.model_validate)`,
which maps each item through the Read schema and carries the cursor across unchanged.
The conversion lives in one place, co-located with `Page`, so no list endpoint
re-assembles the response item-by-item. Endpoints whose items are already the public
type (the `into` aggregates) call it without a mapper.

The module also owns the **request-facing half**: a paginated endpoint declares one
`pagination: PageParams` argument (a `PaginationParams` dependency from
`core/pagination.py`) instead of hand-rolling `cursor`/`limit` parameters, so the
page-size bounds and default live only on that model and flow into every operation
and the OpenAPI document together. Contract tests in `tests/core/test_pagination.py`
enforce the arrangement suite-wide, discovering operations by their `Page` response
envelope — so one that loses its cursor fails the sweep by name instead of dropping
out of it. Every operation serving the envelope must accept a cursor, obtain it via
`PageParams` (no re-declaration anywhere in its dependency tree), and declare the
`invalid_cursor` error mode; an inverse check makes a cursor imply the envelope —
so neither a forgetful new route nor a hand-rolled cursor slips past the module. `PageParams` is a
`Depends()` dependency rather than a `Query()` parameter model because a `Query()`
model silently stops flattening into its fields when the endpoint declares any other
query parameter (all FastAPI versions through 0.139). Endpoints that expose paging
direction consume the shared `OrderParam` declaration the same way, so the `order`
vocabulary and its `asc` default also live only in `core/pagination.py`.

Two things to know if you touch it:

- Keyset columns must be **NOT NULL** (a NULL breaks the row-value comparison and
  silently drops rows). Current keysets are primary keys, NOT NULL columns, or —
  for `/scores/latest` — the owner FK the query already filters to non-NULL.
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
  JSON files in the directory, derives the **Slug** from the `name` field in the
  payload and resolves the app by it, then runs the lifecycle: create Scan Run →
  POST each page → PATCH to Completed. If the app isn't registered it raises
  `AppNotFoundError` pointing you to `import`.
- **`a11y import <dir> --org-unit-id <id> --brand-id <id>`** — onboard an app
  from a directory of `YYYY-MM-DD/` subdirectories, creating the app if missing
  and uploading each date subdirectory as its own Scan Run.

The **Slug** is derived from the axe JSON `name` by the single derivation
function in `core/slug.py` — lowercase ASCII, non-alphanumeric runs collapsed
to hyphens, accents folded — and both name and Slug are immutable after
creation ([ADR 0010](adr/0010-slug-derived-from-axe-name-immutable.md),
[ADR 0019](adr/0019-slug-slugified-and-app-identity-locked-at-creation.md)).
Common CLI failures and what they mean:

| Error | Cause |
| --- | --- |
| `AppNotFoundError` | `ingest` against an app that was never imported |
| `NoDateDirsError` | `import` against a directory with no `YYYY-MM-DD/` subdirs |
| `NameResolutionError` | JSON files missing a `name`, or names that derive to different slugs (different Apps) — presentation-only differences that share a slug resolve to one App, newest scan's variant winning |
| `NameOverrideMismatchError` | `import --name` that doesn't derive to the same slug as the JSON `name` |

### Tracing a request

Endpoint (`api/v1/endpoints/`) → service (`services/`) → model. A failing request
surfaces as a JSON `{"code": …, "message": …}` body (the **Error Contract**'s
`ErrorBody`); the `code` names the exact domain error mode, and the status tells
you which layer rejected it (404/409/400-with-code = a domain exception; 422 =
the request body failed FastAPI's schema validation before any service ran, with
the framework's standard body). Map the code back through the
[`ERROR_MODES` table](#how-errors-become-http-status-codes) to the exception,
then grep for where that exception is raised.

### Inspecting the data

- Every **Page Result** keeps its full axe payload as **Raw JSON** (JSONB) for
  reprocessing and debugging — [ADR 0008](adr/0008-defer-jsonb-by-access-pattern.md)
  explains why it's loaded only on demand.
- Set `DEBUG=true` (see `config.py`) to echo every SQL statement the engine runs.
- `GET /api/v1/health` is the liveness check; Swagger UI is at `/docs`, ReDoc at
  `/redoc`.
