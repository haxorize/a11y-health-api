---
name: fastapi
description: Project conventions for this FastAPI API. Use when creating endpoints, schemas, services, or configuring the app.
---

# FastAPI Project Conventions

## App structure

```
src/a11y_health/
  main.py          # FastAPI app, lifespan, middleware
  config.py        # pydantic-settings Settings singleton
  cli.py           # CLI tools (e.g., ingest, import_app)
  core/
    database.py    # engine, async_session, Base, get_db dependency
    exceptions.py  # domain exceptions raised by services, caught by endpoints
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
7. **Migration** via `alembic revision --autogenerate -m "add <resource>"` — review output, then verify with `alembic downgrade base && alembic upgrade head`

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
      brand_id: Annotated[list[int] | None, Query()] = None,
      cursor: str | None = None,
      limit: Annotated[int, Query(le=100)] = 20,
  ) -> Page[AppRead]: ...
  ```
- Return Pydantic response models with explicit type annotations
- Serialize ORM instances explicitly: `SchemaRead.model_validate(orm_instance)`
- Do not raise `HTTPException` — let domain exceptions propagate to app-level exception handlers (see Error responses)
- Use `async def` — this project uses async SQLAlchemy throughout
- POST endpoints set `status_code=201`, DELETE endpoints set `status_code=204`

## Schemas (Pydantic)

- Pydantic V2 only: `@field_validator` / `@model_validator` (not V1's `@validator`), `model_config = ConfigDict(...)` (not `class Config`), `model_dump()` / `model_validate()` (not `dict()` / `parse_obj()`)
- Use `X | None` (PEP 604) over `Optional[X]`
- Use `Literal` types for constrained string values
- Naming: `<Resource>Create`, `<Resource>Update`, `<Resource>Read`
- Use `model_config = ConfigDict(from_attributes=True)` on Read models
- Do not use `RootModel` for wrapping single values
- Omit deferred columns from Read schemas (see database skill)

## Services

- Accept `AsyncSession` as first parameter
- Return ORM model instances (endpoint serializes via schema)
- Raise domain exceptions (not `HTTPException`) — endpoints catch and translate to HTTP status codes
- One service module per resource; group related operations. Import with alias: `from a11y_health.services import brand as brand_service`
- Cross-cutting orchestration goes in `services/<name>.py` without underscore prefix (e.g., `scoring_orchestration.py`). These modules coordinate multiple resource services for side effects triggered by mutations
- Shared helpers go in `services/_<name>.py` (underscore prefix signals "not a resource service"). These modules can export types and constants used by endpoints too
- Call `flush()` (not `commit()`) — `get_db` commits the transaction automatically on success
- Call `await session.refresh(obj)` after flush to load server-generated values (id, timestamps)
- Define a module-level `_RESOURCE = "ResourceName"` constant for exception messages. For derived resource labels, use f-string composition: `f"{_RESOURCE} summary"`
- Catch `IntegrityError` on flush, match against exported constraint name constants, and raise a domain exception. Use `begin_nested()` to create a savepoint so only the failed flush is rolled back (not the entire transaction):
  ```python
  try:
      async with session.begin_nested():
          await session.flush()
  except IntegrityError as exc:
      if UQ_APP_SLUG in str(exc):
          raise DuplicateSlugError(data.slug) from exc
      raise
  await session.refresh(app)
  ```

## Orchestration

When a mutation triggers cross-service side effects (e.g., score computation + rollup after scan run completion), that orchestration lives in a dedicated orchestration service module — not in endpoints or individual resource services. Resource services call orchestration functions after their own mutation completes:

```python
# services/scoring_orchestration.py — coordinates score + rollup side effects
async def on_scan_run_completed(session: AsyncSession, scan_run: ScanRun) -> None:
    await score_snapshot_service.compute_app_score(session, scan_run)
    app = await app_service.get_app(session, scan_run.app_id)
    await score_snapshot_service.rollup_org_unit_scores(session, app.org_unit_id)
    await score_snapshot_service.rollup_brand_scores(session, app.brand_id)

# services/scan_run.py — calls orchestration after status change
scan_run = await _do_status_update(session, scan_run, data)
if data.status == ScanRunStatus.COMPLETED:
    await scoring_orchestration.on_scan_run_completed(session, scan_run)
```

This keeps endpoints thin (they only call their resource service) and keeps resource services focused on their own domain while the orchestration module coordinates cross-cutting effects.

## Database sessions

`get_db` yields an `AsyncSession` that auto-commits on success and rolls back on exception. Endpoints receive it via `Depends(get_db)`. Session uses `expire_on_commit=False`.

## Config

`pydantic-settings` with `.env` file support. Module-level `settings` singleton. Add `model_validator` checks for production safety (see CORS validation in `config.py`).

## Pagination

Cursor-based pagination via `core/pagination.py`. List endpoints accept `cursor` and `limit`, return `Page[T]` with `items` and `next_cursor` (null when no more pages).

**Endpoint:**
```python
@router.get("")
async def list_apps(
    db: DbSession,
    cursor: str | None = None,
    limit: Annotated[int, Query(le=100)] = 20,
) -> Page[AppRead]:
    page = await app_service.list_apps(db, cursor=cursor, limit=limit)
    return Page(items=[AppRead.model_validate(a) for a in page.items], next_cursor=page.next_cursor)
```

**Service** — keyset pagination (not OFFSET; OFFSET drifts under concurrent inserts and scales poorly). Order by the cursor key, fetch `limit + 1` to detect "more", encode the last visible row's key:
```python
if cursor is not None:
    cursor_id = int(decode_cursor(cursor, expected=1)[0])
    stmt = stmt.where(App.id > cursor_id)
stmt = stmt.order_by(App.id).limit(limit + 1)
rows = list((await session.execute(stmt)).scalars().all())
has_more = len(rows) > limit
items = rows[:limit]
next_cursor = encode_cursor(items[-1].id) if has_more else None
return CursorPage(items=items, next_cursor=next_cursor)
```

**Composite cursor** for non-unique sort keys (e.g. timestamp + id tiebreaker). Use SQL row-tuple comparison so the index can serve it:
```python
decoded = decode_cursor(cursor, expected=2)
cursor_ts = datetime.fromisoformat(decoded[0])
cursor_id = int(decoded[1])
stmt = stmt.where(tuple_(ScoreSnapshot.snapshot_at, ScoreSnapshot.id) > (cursor_ts, cursor_id))
stmt = stmt.order_by(ScoreSnapshot.snapshot_at, ScoreSnapshot.id).limit(limit + 1)
...
next_cursor = encode_cursor(items[-1].snapshot_at, items[-1].id) if has_more else None
```

**Helpers** — `encode_cursor(*values)` → opaque base64; `decode_cursor(cursor, expected=N)` → list (raises `InvalidCursorError`, mapped to 400 in `main.py`). The cursor is opaque to clients; pass `expected=` to enforce arity. Service returns the internal `CursorPage[T]` (dataclass); the endpoint converts to the wire-format `Page[T]` (Pydantic) after validating items.

## Error responses

- Services raise domain exceptions (defined in `core/exceptions.py`)
- `main.py` maps exception classes to HTTP status codes in `_EXCEPTION_STATUS_CODES` and registers handlers in a loop — add new domain exceptions there
- Endpoints never catch or raise `HTTPException` directly
- Pydantic shape errors return 422 — FastAPI's built-in handler covers automatic body validation; the custom `_validation_error_handler` in `main.py` covers explicit `model_validate()` calls (see `pages.py` for an example)
- Status conventions: 404 for missing resources, 409 for domain conflicts (duplicate slug, invalid state transition, has-dependents), 400 for malformed request data (e.g., `InvalidCursorError`)

## Domain exceptions

Exception classes store context as instance attributes before calling `super().__init__()`:
```python
class NotFoundError(Exception):
    def __init__(self, resource: str, resource_id: object) -> None:
        self.resource = resource
        self.resource_id = resource_id
        super().__init__(f"{resource} {resource_id} not found")
```

Follow this pattern for new exceptions — attributes enable structured logging and testing; `str(exc)` provides the HTTP response detail.
