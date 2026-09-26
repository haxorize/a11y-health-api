---
name: fastapi
description: Project conventions for this FastAPI API — app structure, endpoints, schemas, services, pagination, the Error Contract, and domain exceptions. Use when adding or changing an endpoint, schema, service, dependency, or exception class, when declaring error responses, when paginating a list operation, or when configuring the app.
---

# FastAPI Project Conventions

## App structure

```
src/a11y_health/
  main.py          # assemble_application(*, allowed_origins): lifespan, middleware, routers; `app` is its one module-level call
  config.py        # pydantic-settings Settings singleton
  cli/             # Onboarding CLI: _scan (disk), _client (API), _operations (sequences), _terminal (argv), _errors
  core/
    database.py       # SessionSource + its one rebinding point, Base, get_db dependency
    exceptions.py     # domain exceptions raised by services, caught by endpoints
    error_body.py     # ErrorCode + the served/client body shapes (no FastAPI import)
    error_contract.py # ERROR_MODES, the handler, error_responses()
    existence.py      # the Existence Guard: get_by_pk/get_by_query + ENTITY_LABELS
    integrity.py      # the Integrity Guard: guard() turns a named constraint violation into a domain error
    pagination.py     # paginate(): cursor decode, keyset walk, encode
    slug.py           # derive_slug(): an App's Slug from its name, immutable thereafter.
                      # rederive_slugs() is migration-only — its one non-test caller is
                      # the revision that backfilled them (ADR 0019)
  api/
    deps.py        # Annotated type aliases (DbSession, etc.)
    v1/
      router.py    # aggregates endpoint routers under API_V1_PREFIX
      endpoints/   # one module per resource
  models/          # SQLAlchemy ORM models (inherit Base)
  schemas/         # Pydantic request/response models
  services/        # business logic; endpoints stay thin
```

## Adding a new resource

1. **Model** in `models/<resource>.py` — SQLAlchemy ORM class inheriting `Base`
2. **Schemas** in `schemas/<resource>.py` — separate Create, Update, and Read models
3. **Service** in `services/<resource>.py` — async functions taking `AsyncSession`
4. **Endpoint** in `api/v1/endpoints/<resource>.py` — thin router delegating to service
5. **Register** router in `api/v1/router.py`
6. **Re-export** model in `models/__init__.py`
7. **Migration** — the database skill's "After a model change" section owns the sequence

## Endpoints

- One `APIRouter(prefix="/resource-name", tags=[...])` per resource module
- For sub-resources scoped under a parent, export a second router with a nested prefix and register both in `router.py`:
  ```python
  # endpoints/scan_runs.py
  app_router = APIRouter(prefix="/apps/{app_id}/scan-runs", tags=["scan-runs"])
  router = APIRouter(prefix="/scan-runs", tags=["scan-runs"])
  ```
- Prefer `Annotated` for all parameter declarations — `Depends`, `Query`, `Path`, `Body`. Lifts the default to the parameter's `=` slot, so no `Query()` default object and no `# noqa: B008`:
  ```python
  DbSession = Annotated[AsyncSession, Depends(get_db)]


  async def list_apps(
      db: DbSession,
      pagination: PageParams,
      brand_id: Annotated[list[int] | None, Query()] = None,
  ) -> Page[AppRead]: ...
  ```
- Paginated endpoints: see [Pagination](#pagination)
- Return Pydantic response models with explicit type annotations
- Serialize ORM instances explicitly: `SchemaRead.model_validate(orm_instance)`
- Use `async def` — this project uses async SQLAlchemy throughout
- POST endpoints set `status_code=201`, DELETE endpoints set `status_code=204`

## Schemas (Pydantic)

- Pydantic V2 only: `@field_validator` / `@model_validator` (not V1's `@validator`), `model_config = ConfigDict(...)` (not `class Config`), `model_dump()` / `model_validate()` (not `dict()` / `parse_obj()`)
- Use `Literal` types for constrained string values
- Naming: `<Resource>Create`, `<Resource>Update`, `<Resource>Read`
- Use `model_config = ConfigDict(from_attributes=True)` on Read models
- Do not use `RootModel` for wrapping single values
- Deferred columns in Read schemas: see the database skill

## Services

- Accept `AsyncSession` as first parameter
- Return ORM model instances (endpoint serializes via schema). Exception: when a response is assembled from more than one query (e.g. `rule_finding.get_finding` merging a Rule Finding with its Node Findings), the service returns the assembled Read schema and the endpoint just returns it — assembly stays below the transport seam
- Raise domain exceptions — the Error Contract's app-level handler translates them to HTTP
- One service module per resource; group related operations. Import with alias: `from a11y_health.services import brand as brand_service`
- Cross-cutting orchestration goes in `services/<name>.py` without underscore prefix (e.g., `scoring_orchestration.py`). These modules coordinate multiple resource services for side effects triggered by mutations
- Shared helpers go in `services/_<name>.py` (underscore prefix signals "not a resource service"). These modules can export types and constants used by endpoints too
- Call `flush()` (not `commit()`) — `get_db` commits the transaction automatically on success
- Call `await session.refresh(obj)` after flush to load server-generated values (id, timestamps)
- Define a module-level `_RESOURCE = "ResourceName"` constant for exception messages. For derived resource labels, use f-string composition: `f"{_RESOURCE} summary"`
- Writes guarded by a named constraint use `core/integrity.py`'s `guard` — never hand-roll the `begin_nested()`/`IntegrityError` dance. Map exported constraint-name constants to the domain error, building the mapping fresh per call; the mutation goes **inside** the `async with` block (see the `guard` docstring for why):
  ```python
  async with integrity.guard(session, {UQ_APP_SLUG: DuplicateSlugError(slug)}):
      session.add(app)
  await session.refresh(app)
  ```
  On a recognized violation `guard` raises the mapped domain error with the transaction still usable; anything else re-raises unchanged. Classification rules and the single-use-mapping invariant live in `guard`'s docstrings; ADR 0028 records the decisions.

## Orchestration

When a mutation triggers cross-service side effects (e.g., score computation + rollup after scan run completion), that orchestration lives in a dedicated orchestration service module — not in endpoints or individual resource services. Resource services call orchestration functions after their own mutation completes:

```python
# services/scoring_orchestration.py — coordinates score + rollup side effects
async def on_scan_run_completed(session: AsyncSession, scan_run: ScanRun) -> None:
    await score_snapshot_service.compute_app_score(session, scan_run)
    app = await existence.get_by_pk(session, App, scan_run.app_id)
    await on_app_latest_snapshot_changed(session, app)  # → owner.rollup(...) per rollup owner


# services/scan_run.py — update_scan_run_status calls orchestration after the flush
scan_run.status = data.status
await session.flush()
await session.refresh(scan_run)
if data.status == ScanRunStatus.COMPLETED:
    await scoring_orchestration.on_scan_run_completed(session, scan_run)
```

## Database sessions

`get_db` yields an `AsyncSession` from the session source that auto-commits on success and rolls back on exception. Endpoints receive it via `Depends(get_db)`. Session uses `expire_on_commit=False`. The source (`session_source()`) is read at call time by `get_db` and the lifespan. Read it the same way anywhere else: code that captures `session_source()` or its engine at import time keeps the source bound then and never sees a later rebinding (ADR 0011).

## Config

`pydantic-settings` with `.env` file support. Module-level `settings` singleton. Add `model_validator` checks for production safety (see CORS validation in `config.py`).

## Pagination

Cursor-based (keyset) pagination via `core/pagination.py` — one deep module owns both halves (see [ADR 0017](../../../docs/adr/0017-keyset-pagination-deep-module.md) and `docs/architecture.md` "Pagination"):

- **Request surface** — endpoints take one `pagination: PageParams` argument; never declare `cursor`/`limit` locally. Page-size bounds and `DEFAULT_PAGE_SIZE` live on `PaginationParams` only. `PageParams` is a `Depends()` model dependency, not a `Query()` parameter model — a `Query()` model silently stops flattening into its fields when the endpoint has any other query parameter. The repro in `docs/solutions/fastapi-query-model-stops-flattening-beside-other-query-params.md` was swept across 0.115.13 through 0.139.0 and is red on every one. It was never re-run at the pinned 0.141.1, so that version is unmeasured rather than known-red; re-run the repro before treating an upgrade as the fix.
- **Query mechanics** — services call `paginate(session, stmt, keyset=[...], cursor=..., limit=...)`; no service hand-rolls the cursor decode/encode, ordering, or `limit + 1` probe.

**Endpoint:**
```python
@router.get("", responses=error_responses(ErrorCode.INVALID_CURSOR))
async def list_apps(
    db: DbSession,
    pagination: PageParams,
) -> Page[AppRead]:
    page = await app_service.list_apps(db, cursor=pagination.cursor, limit=pagination.limit)
    return Page.from_cursor_page(page, AppRead.model_validate)
```

**Service:**
```python
async def list_apps(
    session: AsyncSession, *, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
) -> CursorPage[App]:
    return await paginate(session, select(App), keyset=[App.id], cursor=cursor, limit=limit)
```

Use a composite keyset for non-unique sort keys (timestamp + id tiebreaker): `keyset=[ScoreSnapshot.snapshot_at, ScoreSnapshot.id]`. Keyset columns must be NOT NULL.

**Enforcement** — contract tests in `tests/core/test_pagination.py` sweep every served operation. Accepting a cursor requires consuming `PageParams` and declaring `ErrorCode.INVALID_CURSOR` (raised by `paginate` on a malformed cursor, mapped to 400 by the Error Contract). The sweep reaches sub-dependencies, so a shared dependency growing its own `cursor` or `limit` fails the rule above as well: two definitions of one wire parameter publish conflicting schemas. A forgotten declaration fails the suite, not review.

Service returns the internal `CursorPage[T]` (dataclass); the endpoint converts to the wire-format `Page[T]` (Pydantic) with `Page.from_cursor_page`.

## Error responses

- Services raise domain exceptions — subclasses of `DomainError` (defined in `core/exceptions.py`)
- `core/error_contract.py` owns the Error Contract: the `ERROR_MODES` table maps each exception type to its status and machine-readable `ErrorCode`; the handler, the shared `ErrorBody` body (`{"code", "message"}`), and per-operation OpenAPI declarations all derive from it
- Every operation declares the modes that can escape it: `@router.get(..., responses=error_responses(ErrorCode.NOT_FOUND, ...))` — declare in domain vocabulary, never write a status code in an endpoint
- Endpoints never catch or raise `HTTPException` directly
- 422 belongs to the framework: only FastAPI's own request-shape validation produces it, with the standard body. Well-formed requests failing domain validation return 400 with a coded body (`invalid_cursor`, `invalid_axe_payload`) — do not add app-level `ValidationError` handlers; wrap explicit `model_validate()` calls at the boundary into a domain error instead (see `parse_axe_payload` in `schemas/axe_payload.py`)
- Adding a mode: subclass `DomainError`, add the `ERROR_MODES` row + `ErrorCode` member, declare it on the operations that raise it. The exhaustiveness test and the suite-wide declaration-honesty shim (`tests/_declaration_honesty.py`, which owns the whole mechanism and reads declarations through the contract's `ERROR_CODES_KEY`) fail on gaps
- Status conventions: 404 for missing resources, 409 for domain conflicts (duplicate slug, invalid state transition, has-dependents), 400 for well-formed-but-domain-invalid data

## Domain exceptions

Exception classes subclass `DomainError` and store context as instance attributes before calling `super().__init__()`. `DuplicateSlugError` is the shape, quoted as it stands in `core/exceptions.py`:
```python
class DuplicateSlugError(DomainError):
    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"App with slug '{slug}' already exists")
```

Follow this pattern for new exceptions — attributes enable structured logging and testing; `str(exc)` provides the HTTP response detail.

**Open a new message on a literal rather than on an interpolated value** — a message pasted from a log or a bug report has to grep back to the one line that raises it, and a leading `{resource}` leaves only the tail to search for. This is a rule for messages not yet written: five of the ten current subclasses open interpolated, `NotFoundError` among them. Their text is the served body — `core/error_contract.py` sends `str(exc)` — so rewording one moves `openapi.json`, the UI's generated client, and three tests that pin the exact string (`tests/core/test_error_contract.py`, `tests/core/test_existence.py`). #184 owns that sweep; until it lands, **when rewording an existing message** match the file rather than the rule — a message written new follows the rule.
