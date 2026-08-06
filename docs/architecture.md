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

`models/` also holds the layer-neutral leaves that every other layer needs and
none of them owns. `models/classification.py` is the one to know: the
**Classification** value object *and* the closed **Classification Token**
vocabulary that names it — the query tokens the findings endpoint declares, the
canonical mint for the stored shape, the **Filter Options** enumeration, and the
screen that names a rule's raw axe tags at ingest — kept together so the
import-time drift guard that pins them to each other has both halves in front of
it. Every read runs the same closed table, so a token cannot mean one thing to a
query and another to an ingest. It lives here because its consumers span layers
(findings endpoint, filter service, read schema, column type, axe boundary);
putting it in `schemas/` would send three of those five across a seam, and
`services/` four
([ADR 0031](adr/0031-typed-classification-compact-wire-shape.md)).

**`core/`** holds the cross-cutting machinery every layer leans on: `database.py`
(engine, session, base classes), `pagination.py` (see [Pagination](#4-pagination)),
`exceptions.py` (the domain error types), `error_contract.py` (the **Error
Contract** — how domain errors become HTTP responses and contract declarations),
and `existence.py` (the **Existence Guard** — see below).

### Underscore means package-private, and a test says so

A source module whose name starts with `_` may be reached from within its own
package and nowhere else — `schemas/_tag_parsing.py` is axe-tag ingest parsing
for `schemas/axe_payload.py`; `services/_latest_snapshot.py` serves the **Owner
Dispatcher**; `services/_org_subtree.py` serves three consumers inside
`services/` (`owner.py`, `org_unit.py`, and `app.py`). A private *package* gates
everything beneath it, so a public module inside one is not a way in.
`tests/test_import_honesty.py` walks the source tree and fails on any crossing,
in either import spelling, so the underscore is a checked claim rather than a
hint. The rule covers the package and nothing else — tests, migrations, and
scripts sit outside it, which is what lets a private module's own suite import
it directly. [ADR 0038](adr/0038-package-private-underscore-enforced-repo-wide.md)
records why this is enforced rather than conventional.

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

**Listing parameters split on whether the guard applies at all.** A *scope* —
`/scores/latest`'s `brand_id` and `under_org_unit_id` — names one entity the
answer is computed *relative to*, so it is guarded and an unknown id 404s. A
*filter* — the apps listing's `brand_id`/`org_unit_id`, the org-units listing's
`parent_id`, `/scores/latest`'s `owner_id` — narrows a set by matching values,
takes a list, and is not guarded: unknown ids match nothing, and guarding would
run an existence query per value to reject a request whose answer is already
well-defined. A new listing parameter picks the side it belongs to rather than
splitting the difference.

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

The dependency is declared `Depends(get_db, scope="function")` (`api/deps.py`)
so the commit lands **before the response is sent**. FastAPI's default
`"request"` scope runs yield-dependency teardown after the response, which
races a sequential client: it can receive a 201, immediately GET the new
resource, and 404 because the creating request hasn't committed yet (observed
as e2e seed flake in a11y-health-ui CI).

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
codes under `ERROR_CODES_KEY` — the vendor extension `x-error-codes`).

| Mode (exception → code) | Status |
| --- | --- |
| `NotFoundError` → `not_found` | 404 |
| `CircularReferenceError` → `circular_reference`, `ConcurrentRollupError` → `concurrent_rollup`, `DuplicateSlugError` → `duplicate_slug`, `EmptyScanRunError` → `empty_scan_run`, `HasDependentsError` → `has_dependents`, `InvalidStatusTransitionError` → `invalid_status_transition`, `ScanRunCompletedError` → `scan_run_completed` | 409 |
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

When the *database* is the rule's enforcer (a constraint backing a domain
invariant, like the single **Root Org Unit**, the unique **Slug**, or the
**Dependents Guard**'s RESTRICT FKs), services don't inspect `IntegrityError`
themselves: they declare a constraint→error mapping and `core/integrity.py`'s
`guard` — the **Integrity Guard** — translates a recognized violation into its
mapped domain error with the surrounding transaction still usable, re-raising
anything unrecognized. How violations are identified, and the SQLAlchemy
subtlety that forces the guarded mutation *inside* the `guard` block, live in
the module's docstrings; [ADR 0028](adr/0028-integrity-guard-constraint-identity-savepoint.md)
records the decisions.

So: to add a new failure mode, subclass `DomainError`, add its row to
`ERROR_MODES`, and list its code in `error_responses(...)` on the operations
that can produce it. An exhaustiveness test fails if a `DomainError` subclass
lacks a table entry, and the test suite's declaration-honesty shim (the ASGI
wrapper in `tests/_declaration_honesty.py`) fails any test that observes an
undeclared error status or code. That module holds the whole mechanism — the
audit that reads a declaration as well as the plumbing that applies it — and
reads what `error_responses(...)` wrote through the contract's shared
`ERROR_CODES_KEY`. The endpoint logic stays untouched.

One mode can't be caught at the response: rollup-race 409s
(`concurrent_rollup`) never fire organically in endpoint tests. The same test
module closes that gap at the *raise site* instead — it instruments the
public `rollup*` callables on the Owner Dispatcher (`services/owner.py`)
through which `ConcurrentRollupError` can escape, and any operation observed
reaching one during a request fails immediately unless it declares the retryable
mode. Rollups fire on success paths, so enforcement reaches as deep
as the suite drives rollup-triggering variants — each known rollup-triggering
operation is pinned by an explicit HTTP canary in
`tests/test_declaration_honesty.py`, and a structural test pins the
attribute-access calling convention the instrumentation relies on (#113; ADR
0033 records the residuals).

The reverse direction — an operation still declaring `concurrent_rollup`
after its rollup call is removed — is caught at session finish (#121): on a
green full-suite run, `conftest.py` diffs the operations declaring the mode
against those observed reaching a rollup and fails the run on any stale
declaration. Narrowed runs (positional paths, `--ignore`, deselection, or a
mode that executes no tests) skip the diff, since a subset legitimately
observes nothing for the operations it never drove; a red run also skips it,
so a stale declaration surfaces on the next green full run.

---

## 2. The scoring & rollup model

This is the heart of the system and the part worth reading slowly. The code
splits as computation vs. dispatch: `services/score_snapshot.py` computes the
app score (findings → Page Health → Score), and `services/owner.py` — the
**Owner Dispatcher** — owns everything per-owner: snapshot construction, the
latest/history score reads, and the rollups. Terms: **Page Health**, **Score**,
**Score Snapshot**, **Rollup**, **Owner Dispatcher** — all in `DOMAIN.md`.

The *meaning* behind the scoring value sets — the health ordering (worst → best,
each health's rank derived from its position), the health weights, and the total
Impact → Page Health mapping — has one home: the **Scoring Vocabulary** module,
`services/scoring_vocabulary.py`. The scoring engine imports it, and
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
than one ([ADR 0002](adr/0002-score-snapshot-mutex-owner.md)) — and construction
is owner-typed: `owner.owned()` picks the owner column from the spec table, so
exactly-one-owner holds structurally, with the database check constraint as the
backstop. Everything per-owner routes through the Owner Dispatcher's `OWNERS`
spec table, derived from one exhaustive match over the owner enum — a missing
owner case fails type checking, and adding an owner type touches exactly one
module. The table is also the sanctioned test seam: the rollup-race harness
swaps the whole table for a test's duration, and consumers resolve it at call
time ([ADR 0037](adr/0037-per-owner-variation-concentrates-in-the-owner-dispatcher.md)).
The module's charter is closed both ways: app-score computation stays out, and
no per-owner dispatch may exist anywhere else. There are two rollup shapes,
behind one `owner.rollup(session, owner_type, owner_id)` entrypoint:

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
as "latest" can never disagree with what rollups aggregate. That endpoint's
`owner_id` filter is exact-match, unlike the apps listing's
descendant-expanding `org_unit_id`: a rollup owner's snapshot already
aggregates everything it covers, so expansion would double-count. Any future
owner-valued filter on a scores read should follow the exact-match side of
that split. The `under_org_unit_id` scope is the sanctioned other side — it
names a *place* in the org tree, not owners, and resolves per owner type:
`app` serves apps placed anywhere in the unit's subtree (the unit's own apps
included, matching the apps listing), `org_unit` serves the units strictly
below it (the named unit is not "under" itself, and its own rollup already
aggregates the subtree), and `brand` serves the empty set (brands have no
org-tree placement). The scope's `direct_only` opt-in narrows that resolution one step per owner
type — `app` serves apps placed exactly on the named unit, `org_unit` its
depth-1 children, `brand` stays empty — so a caller rendering only a unit's
direct rows can fetch a response that matches them instead of the whole
subtree. Without `under_org_unit_id` there is no scope to refine, so
`direct_only` is ignored
([ADR 0035](adr/0035-direct-only-opt-in-refines-the-under-org-unit-scope.md)).
The `brand_id` scope names a *brand*, not owners,
and resolves the same way: `app` serves the brand's apps wherever they sit in
the org tree (flat, like the Brand Rollup), while `org_unit` and `brand` serve
the empty set — org units carry no brand, and the scoping brand's own rollup
already aggregates the scoped apps (fetch it via `owner_id`). Both scopes and
`owner_id` intersect when sent together — never mutually exclusive
([ADR 0036](adr/0036-brand-scope-resolves-per-owner-type.md)).

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
> since been deleted. Since #98 the database enforces this for rollup owners:
> partial unique indexes on (owner, `snapshot_at`) decide same-observation write
> races, the losing rollup failing as `ConcurrentRollupError` (409, retryable). App snapshots stay
> unconstrained — two Scan Runs may share an observation time (ADR 0015).
>
> **Concurrency model.** Recomputes for one owner are serialized by a
> transaction-scoped advisory lock acquired as the rollup's first statement —
> before the children read — so a rollup deriving an older observation can
> never prune or displace a newer one committed concurrently: the two
> different-observation rows never collide, which puts that interleaving beyond
> what the #98 indexes can decide
> ([ADR 0029](adr/0029-per-owner-advisory-lock-rollup-serialization.md), #101).
> Locks are per owner (org unit or brand), acquired leaf-to-root along the
> cascade. The two-subtree triggers — app reassignment and org-unit
> reparenting — break that single order (the second subtree's locks are taken
> after the root is already held) and can deadlock with any concurrent rollup;
> Postgres detects the cycle and fails one transaction (ADR 0029). The loser's
> `40P01` is translated at the lock acquisition into the retryable
> `concurrent_rollup` 409 (#104), declared on every rollup-triggering
> operation. The indexes stay the backstop for same-observation races,
> unchanged.

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
the ancestors traversal — deliberately return bare arrays instead;
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

An operation whose consumers need the **exact filtered count** opts into the
**totalled** envelope: the service passes `with_total=True` and `paginate` also
serves `total`, counted from the same statement the page runs over so the two can
never disagree on which rows are in scope (the count is skipped when the first
page is also the last). The equivalence is of scope, not snapshot: the count is a
second query, so a write committed between the two can shift `total` relative to
the page until the next fetch — acceptable for a result-count announcement. The pair `TotalledCursorPage`/`TotalledPage` extends the
plain envelope per-operation — every other listing keeps its two-field shape and
pays no count query. Today the findings listing (its UI announces "N results"
after a filter change) and an app's scan-run listing (its UI's history count
line) are totalled; the conformance sweep requires any totalled operation to
publish `total` as a required response property.

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
  lists return ORM objects directly; `list_page_metrics` and `list_findings` use
  `into` to shape aggregate query rows into their Read models.

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

`cli/` (`uv run a11y …`) is a thin client that drives the *public API over
HTTP* — it has no direct database access, so anything it does, you could do with
`curl`. It splits by concern over the shared error base in `_errors`: `_scan`
reads directories off disk, `_client` makes the requests (one function per
call), `_operations` sequences those two into the commands below, and
`_terminal` parses argv and prints. `_scan` and `_client` never import each
other, which is what lets a failure that happens before the first request be
tested with no server at all (`tests/cli/conftest.py`'s `no_server`). Two
commands, chosen by app state:

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
Every failure an operator can cause is a named subclass of `CliError`, which is
the only *error* `main()` catches: it prints one `ERROR:` line and exits 1.
Anything else keeps its traceback, because anything else is a bug. Ctrl-C is
neither — it prints `Interrupted.` and exits 130, leaving any Scan Run created
before the interrupt Pending and unscored.

| Error | Cause |
| --- | --- |
| `AppNotFoundError` | `ingest` against an app that was never imported |
| `ApiUnreachableError` | the server isn't running, or `--base-url` points somewhere else |
| `ApiTimeoutError` | the server answered the connection but not the request in time |
| `UnreadableApiResponseError` | a success status carrying a body that isn't JSON — `--base-url` names something that isn't this API |
| `NoDateDirsError` | `import` against a directory with no `YYYY-MM-DD/` subdirs |
| `NameResolutionError` | JSON files missing a `name`, or names that derive to different slugs (different Apps) — presentation-only differences that share a slug resolve to one App, newest scan's variant winning |
| `NameOverrideMismatchError` | `import --name` that doesn't derive to the same slug as the JSON `name` |
| `MissingScanDirectoryError` | the scan directory doesn't exist |
| `EmptyScanDirectoryError` | the scan directory holds no `*.json` |
| `MalformedScanFileError` | a scan file isn't valid JSON, isn't valid UTF-8, or holds something other than a JSON object |
| `UnparseableScanTimestampError` | a scan file's `endTime` isn't a readable ISO timestamp |
| `UnderivableAppNameError` | a `name` (or `import --name`) that derives to an empty or over-long slug |

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
