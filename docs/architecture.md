# Architecture

Written for an engineer new to this service: the cross-cutting behavior no single file carries.

`DOMAIN.md`, the glossary, defines the domain terms bolded here (**Scan Run**, **Page Health**, **Score Snapshot**, **Axe Boundary**, and the rest); read it first if a word is unfamiliar. `docs/adr/` is the decision log, linked below wherever a choice is non-obvious. [`docs/operating.md`](operating.md) is the operating companion: how a change is checked, the CLI, the same three calls without the CLI, tracing a request, inspecting the data.

---

## 1. The layers

A request flows through three layers to Postgres, each with one job, and only the liveness check skips them; `schemas/` and `core/` below sit beside that flow rather than in it.

```
HTTP request
   │
   ▼
endpoint   api/v1/endpoints/*.py
   │
   ▼
service    services/*.py
   │
   ▼
model      models/*.py
   │
   ▼
PostgreSQL
```

- **Endpoints** (`api/v1/endpoints/`) declare the URL, accept a request validated by a schema, hand off to a service, and convert the result into a response schema. Logic found in an endpoint belongs in a service.
- **Services** (`services/`) own the queries, the validation that needs the database, and the domain operations. They take a session plus plain arguments and return ORM objects or a `CursorPage`, almost never HTTP types, so tests can call them without the web layer. **Page Result** creation alone takes a raw document, crossing the **Axe Boundary** itself so the `invalid_axe_payload` mode is its own ([ADR 0009](adr/0009-axe-payload-pydantic-boundary.md)).
- **Models** (`models/`) are SQLAlchemy table definitions, and they hold the layer-neutral leaves no other layer owns. `models/classification.py` holds the **Classification** value object and the **Classification Token** vocabulary naming it, kept together because its five production consumers span layers, the roster and the placement argument in [ADR 0031](adr/0031-typed-classification-compact-wire-shape.md).
- **Schemas** (`schemas/`) are Pydantic request and response bodies, kept apart from the models so stored and wire shapes evolve independently.
- **`core/`** holds the cross-cutting machinery every layer uses: `database.py`, `error_body.py`, `error_contract.py`, `exceptions.py`, `existence.py`, `integrity.py`, `pagination.py`, and `slug.py`.

A whole endpoint is usually three lines under its decorator, whose `responses=` argument declares the operation's error modes (see [How errors become HTTP status codes](#how-errors-become-http-status-codes)). `DbSession` comes from `api/deps.py`:

```python
@router.post("", status_code=201, responses=error_responses(ErrorCode.NOT_FOUND, ErrorCode.DUPLICATE_SLUG))
async def create_app(db: DbSession, data: AppCreate) -> AppRead:
    app = await app_service.create_app(db, data)
    return AppRead.model_validate(app)
```

### Underscore means package-private

A source module whose name starts with `_` may be reached from within its own package and nowhere else, and a private package gates everything beneath it. `tests/test_import_honesty.py` fails on any private-module import from outside, the walk covering the installed package so tests, migrations, and scripts sit outside the rule ([ADR 0038](adr/0038-package-private-underscore-enforced-repo-wide.md)).

### The Existence Guard and the two-tier call rule

One module owns checking that a referenced entity exists: `core/existence.py`. Its two entry points, `get_by_pk` and `get_by_query`, each return the entity or raise `NotFoundError` with the entity's label from the module's one closed label table. `tests/core/test_existence.py` fails if any other module raises `NotFoundError`; the label table's exclusivity is convention, not a checked claim.

Callers follow a two-tier call rule:

- **Each entity's own service keeps its named accessors** (`get_app`, `get_brand`, and the rest), delegating to the guard. Endpoints read through these, never through the guard.
- **Every other module calls the guard directly**, with the model class. No service imports a sibling service just to ask whether something exists; `tests/core/test_existence.py` checks that, and the **Sibling-Import Rule** in `DOMAIN.md` records the wider invariant.

Listing parameters split on whether the guard applies. A scope, such as `/scores/latest`'s `under_org_unit_id`, names one entity the answer is relative to, so it is guarded and an unknown id returns 404. A filter, such as the apps listing's `org_unit_id`, narrows by matching values and is not guarded: unknown ids match nothing. A new parameter picks a side ([ADR 0024](adr/0024-existence-guard-core-module-two-tier-rule.md)).

### How the database session and transactions work

`core/database.py`'s `get_db()` opens one session per request from the session source and wraps it in a transaction: commit on success, roll back on any exception. The source holds the engine, and `get_db` and the startup probe both read it at call time, so `bind_session_source` is the one place the suite points the application at its own database. Services and endpoints therefore never call `commit()` themselves; they call `flush()` for a generated id mid-request.

The dependency is declared `Depends(get_db, scope="function")` so the commit lands before the response is sent; `docs/solutions/yield-teardown-commit-races-next-request.md` records the race that forced it. A session is not safe to share across concurrent tasks ([ADR 0007](adr/0007-async-session-not-concurrency-safe.md)), and tests rely on the rollback for isolation ([ADR 0011](adr/0011-transactional-rollback-test-isolation.md)).

### How errors become HTTP status codes

Services raise semantic exceptions, subclasses of `DomainError`, and know nothing about HTTP. `core/error_contract.py` owns the **Error Contract**: one table, `ERROR_MODES`, maps each mode to its status and its **Error Code**, and the runtime handler, the shared `ErrorBody` shape, and each operation's OpenAPI declaration all derive from it.

| Mode (exception, and its code) | Status |
| --- | --- |
| `NotFoundError` (`not_found`) | 404 |
| `CircularReferenceError` (`circular_reference`), `ConcurrentRollupError` (`concurrent_rollup`), `DuplicateRootError` (`duplicate_root`), `DuplicateSlugError` (`duplicate_slug`), `EmptyScanRunError` (`empty_scan_run`), `HasDependentsError` (`has_dependents`), `InvalidStatusTransitionError` (`invalid_status_transition`), `ScanRunCompletedError` (`scan_run_completed`) | 409 |
| `InvalidCursorError` (`invalid_cursor`), `InvalidAxePayloadError` (`invalid_axe_payload`) | 400 |
| Pydantic `ValidationError`, where the request never matched the declared schema | 422 |

The 400-versus-422 rule: 422 belongs to the framework, while a well-formed request failing domain validation returns 400 with a coded body. No app-level handler catches `ValidationError`, because an internal validation failure escaping the domain is a defect and returns a 500 ([ADR 0022](adr/0022-error-contract-single-table-400-vs-422.md)).

Where the database is the rule's enforcer, as with the **Root Org Unit** or the **Dependents Guard**, services declare a constraint-to-error mapping instead of inspecting `IntegrityError`. `core/integrity.py`'s `guard`, the **Integrity Guard**, translates a recognized violation into its domain error with the transaction still usable ([ADR 0028](adr/0028-integrity-guard-constraint-identity-savepoint.md)).

To add a failure mode: subclass `DomainError`, add its row to `ERROR_MODES`, and list its code in `error_responses(...)`. `tests/core/test_error_contract.py` fails if a subclass lacks a table entry, and the declaration-honesty check fails any test observing an undeclared status or code; what it reaches is [ADR 0033](adr/0033-rollup-race-declaration-enforced-at-raise-site.md).

---

## 2. The scoring & rollup model

The code splits as computation versus dispatch. `services/score_snapshot.py` computes the app score, from findings to **Page Health** to **Score**. `services/owner.py`, the **Owner Dispatcher**, owns everything per owner: snapshot construction, the latest and history score reads, the rollups, and the owner-agnostic **Score Aggregates** value those consume.

The health ordering, the health weights, and the total **Impact** to **Page Health** mapping have one home: `services/scoring_vocabulary.py`, the **Scoring Vocabulary**. The tables and weights quoted below illustrate that vocabulary; they are not a second authority. The scoring engine imports it, and `GET /scoring-vocabulary` serves the deployed server's copy so no client hard-codes it ([ADR 0020](adr/0020-scoring-vocabulary-runtime-endpoint.md)).

### Step 1: each page gets a Page Health

A **Page Result**'s health is decided by the worst **Impact** among its **Violation** findings. **Incompletes** never count: they are stored for manual review but excluded from every score ([ADR 0006](adr/0006-incompletes-excluded-from-score.md)). The mapping is lossy and total: every **Impact** maps explicitly, so there is no "unmapped means Good" default. A page with no violations is Good; that empty case belongs to the engine.

| Worst violation impact | Page Health |
| --- | --- |
| critical | Critical |
| serious | Serious |
| moderate | Fair |
| minor | Good |

**Page Health** uses its own words at the 2 higher levels, so "the page is Fair" is never confused with "a finding is moderate" ([ADR 0005](adr/0005-page-health-distinct-from-impact.md)).

### Step 2: the app's Score is a weighted average of its pages

Each **Page Health** carries a weight in the vocabulary: Critical 0, Serious 0.4, Fair 0.8, Good 1.0. The **Score** is the mean of those weights across all pages:

```
score = (0·critical_pages + 0.4·serious_pages + 0.8·fair_pages + 1.0·good_pages) / total_pages
```

The result is saved as a **Score Snapshot** holding the **Score Aggregates**: the score plus the raw counts of total pages, total violations, pages with violations, and pages with critical violations. An app snapshot's `snapshot_at` is the **Scan Run**'s `scanned_at`, the observation time rather than the upload time.

### Step 3: the score rolls up to Org Units and Brands

A **Score Snapshot** belongs to exactly one of an App, an Org Unit, or a Brand ([ADR 0002](adr/0002-score-snapshot-mutex-owner.md)), and owner-typed construction holds that structurally. Everything per owner routes through the **Owner Dispatcher**'s `OWNERS` spec table, one exhaustive match over the owner enum, so a new owner type touches one module ([ADR 0037](adr/0037-per-owner-variation-concentrates-in-the-owner-dispatcher.md)). There are 2 rollup shapes, behind one `owner.rollup` entrypoint:

- **Org Unit Rollup is hierarchical and cascades.** A unit recomputes from its children's latest snapshots, apps and units alike, then repeats on its parent to the root.
- **Brand Rollup is flat.** A brand aggregates its apps' latest snapshots at once, wherever they sit in the org tree ([ADR 0004](adr/0004-org-unit-rollup-cascades-brand-rollup-flat.md)).

"Latest" has one definition, newest `snapshot_at` with ties broken by `id`, per owner. `services/_latest_snapshot.py` owns it, and both rollup shapes and the `GET /scores/latest` read share it ([ADR 0023](adr/0023-scores-latest-read-endpoint.md)), so a dashboard's "latest" cannot disagree with what rollups aggregate. That read also takes 2 scopes beside its exact-match `owner_id` filter, each resolving per owner type ([ADR 0034](adr/0034-under-org-unit-scope-resolves-per-owner-type.md), [ADR 0036](adr/0036-brand-scope-resolves-per-owner-type.md)); `direct_only` refines one of them rather than adding a third ([ADR 0035](adr/0035-direct-only-opt-in-refines-the-under-org-unit-scope.md)).

A parent's score is the unweighted arithmetic mean of its children's scores, so a 2-page app and a 2000-page app count equally, while the count columns are summed totals. A share derived from those counts is therefore page-weighted and can diverge from the score itself. Both live on **Score Aggregates**.

Three rules govern how a rollup writes. Snapshots are append-only, so a rollup inserts rather than mutates, and first deletes any owner snapshot dated after the new row's observation time, or all of them where no children are left ([ADR 0015](adr/0015-score-snapshot-append-only.md)). One observation time carries at most one snapshot per rollup owner: an unchanged recompute records nothing, a changed one replaces the rows sharing that time, and only a newer time appends. App snapshots stay unconstrained, since two Scan Runs may share an observation time. Recomputes for one owner are serialized by a blocking advisory lock ([ADR 0029](adr/0029-per-owner-advisory-lock-rollup-serialization.md)), with partial unique indexes deciding same-observation races ([ADR 0015](adr/0015-score-snapshot-append-only.md)); ordinary contention waits its turn, while a deadlock or a lost index race surfaces as `ConcurrentRollupError`, a retryable 409, through the Integrity Guard ([ADR 0028](adr/0028-integrity-guard-constraint-identity-savepoint.md)).

Nothing in this repo retries that 409; the message tells the caller to reissue the request.

### What triggers a rollup

`services/scoring_orchestration.py` is the switchboard: any event changing an app's latest snapshot fires the appropriate rollups:

| Event | What recomputes |
| --- | --- |
| Scan Run completed | app score, then its org-unit chain and its brand |
| Scan Run deleted | the app's org-unit chain and brand |
| App deleted | the former org-unit chain and brand |
| App reassigned to a new Org Unit | both old and new org-unit chains |
| Org Unit reparented | both old and new parent chains |

---

## 3. The scan-run lifecycle

A **Scan Run** is a small state machine, held across `services/scan_run.py` and `services/page_result.py`:

```
            add Page Results                 transition
   ┌───────────────────────────┐         (triggers scoring)
   │                           ▼                  │
[ PENDING ] ─────────────────────────────► [ COMPLETED ]   (terminal)
```

- A run is created **Pending**. Pages may be added only while Pending; posting one to a Completed run raises `ScanRunCompletedError`, a 409, from `services/page_result.py`.
- The only legal transition is Pending to Completed (`_VALID_TRANSITIONS`). Anything else raises `InvalidStatusTransitionError`, a 409. Completed is terminal.
- Completing requires at least one **Page Result**. An empty run raises `EmptyScanRunError`, a 409, because its snapshot would score "no data" as 0.0 and roll that up into every ancestor mean ([ADR 0044](adr/0044-an-unscored-scan-run-never-mints-a-score-snapshot.md)).
- The Pending to Completed transition triggers scoring: it calls `on_scan_run_completed`, which computes the app score and runs both rollups (see [The scoring & rollup model](#2-the-scoring--rollup-model)).

The order is therefore always create run, add pages, complete run (see [Operating & debugging](operating.md)).

---

## 4. Pagination

Every unbounded list endpoint follows the **Cursor Pagination** contract, keyset paginated through one shared function, `paginate()` in `core/pagination.py` ([ADR 0017](adr/0017-keyset-pagination-deep-module.md)). Bounded reference collections return bare arrays; the test is whether the collection can grow without bound ([ADR 0025](adr/0025-bounded-reference-lists-stay-bare-arrays.md)).

A caller passes a filtered query plus the keyset, the columns that order and tiebreak the results, and `paginate` applies the cursor, orders, fetches one row past the limit to detect more, slices, and encodes the `next_cursor`. Paging is forward-only, tiebroken by `id`, and ascending unless the operation says otherwise; the three score-history listings let the client pick with `order=asc|desc`. The endpoint turns the internal `CursorPage` into the public `Page` through `Page.from_cursor_page`, calling the converter without a mapper where the items are already the public type; a totalled page uses `TotalledPage.from_totalled_cursor_page` instead.

An operation needing the exact filtered count opts into the totalled envelope, where `paginate` also serves `total`, counted from the same statement the page runs over. The count is a second query, skipped where the first page is also the last, so it matches the page's scope but not always its instant ([ADR 0032](adr/0032-filtered-total-as-per-operation-totalled-page.md)).

The module owns the request-facing half too: an endpoint declares one `pagination: PageParams` argument, so the page-size bounds and default reach every operation and the OpenAPI document. `tests/core/test_pagination.py` fails any operation that breaks that, and `docs/solutions/fastapi-query-model-stops-flattening-beside-other-query-params.md` says why it is a `Depends()` dependency.

When you touch it:

- **Keyset columns must be `NOT NULL`.** A NULL breaks the row-value comparison and silently drops rows.
- **An optional `into` callback maps each row into a response object.** `list_page_metrics` and `list_findings` use it.

---

## 5. The OpenAPI contract pipeline

The API is the source of truth for the contract the UI consumes. The full cross-repo flow is the `contract-change` skill (`.claude/skills/contract-change/`); the API-side essentials:

- **`make openapi` writes a deterministic `openapi.json`**, committed alongside code so contract changes show up in PR diffs.
- **`make openapi-check` fails the CI lint job if `openapi.json` is stale**, so a contract change cannot merge without its regenerated spec.
- **Each endpoint's operation id is its route function name** (`_operation_id` in `main.py`), and that name becomes the UI's generated method name. Two endpoint functions may therefore not share a name across routers: FastAPI warns and writes the duplicate, which is an invalid OpenAPI document and breaks UI codegen, so `tests/test_main.py` fails on one.
