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
  cli.py           # CLI tools (e.g., upload_scan, bulk_import)
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
- Prefer `Annotated` type aliases for dependency injection:
  ```python
  DbSession = Annotated[AsyncSession, Depends(get_db)]
  ```
- Return Pydantic response models with explicit type annotations
- Serialize ORM instances explicitly: `SchemaRead.model_validate(orm_instance)`
- Do not raise `HTTPException` — let domain exceptions propagate to app-level exception handlers (see Error responses)
- Use `async def` — this project uses async SQLAlchemy throughout
- POST endpoints set `status_code=201`, DELETE endpoints set `status_code=204`

## Schemas (Pydantic)

- Use `Literal` types for constrained string values
- Naming: `<Resource>Create`, `<Resource>Update`, `<Resource>Read`
- Use `model_config = ConfigDict(from_attributes=True)` on Read models
- Do not use `RootModel` for wrapping single values
- Omit deferred columns from Read schemas (see sqlalchemy skill)

## Services

- Accept `AsyncSession` as first parameter
- Return ORM model instances (endpoint serializes via schema)
- Raise domain exceptions (not `HTTPException`) — endpoints catch and translate to HTTP status codes
- One service module per resource; group related operations
- Shared helpers go in `services/_<name>.py` (underscore prefix signals "not a resource service"). These modules can export types and constants used by endpoints too (e.g., `Classification` from `_tag_parsing.py`)
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

## Database sessions

`get_db` yields an `AsyncSession` that auto-commits on success and rolls back on exception. Endpoints receive it via `Depends(get_db)`. Session uses `expire_on_commit=False`.

## Config

`pydantic-settings` with `.env` file support. Module-level `settings` singleton. Add `model_validator` checks for production safety (see CORS validation in `config.py`).

## Pagination

Use offset/limit with sensible defaults:
```python
@router.get("/items")
async def list_items(
    db: DbSession,
    offset: int = 0,
    limit: int = Query(default=20, le=100),
) -> list[ItemRead]: ...
```

## Error responses

- Services raise domain exceptions (defined in `core/exceptions.py`)
- `main.py` maps exception classes to HTTP status codes in `_EXCEPTION_STATUS_CODES` and registers handlers in a loop — add new domain exceptions there
- Endpoints never catch or raise `HTTPException` directly
- Let FastAPI's built-in 422 handling cover Pydantic schema validation errors
- Use 404 for missing resources, 409 for domain conflicts, 422 for domain payload validation (e.g., `InvalidAxePayloadError`)

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
