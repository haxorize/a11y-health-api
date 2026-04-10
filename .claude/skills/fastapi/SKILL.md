---
name: fastapi
description: Project conventions for this FastAPI + async SQLAlchemy API. Use when creating endpoints, models, schemas, services, or configuring the app.
---

# FastAPI Project Conventions

## App structure

```
src/a11y_health/
  main.py          # FastAPI app, lifespan, middleware
  config.py        # pydantic-settings Settings singleton
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
- Prefer `Annotated` type aliases for dependency injection:
  ```python
  DbSession = Annotated[AsyncSession, Depends(get_db)]
  ```
- Return Pydantic response models with explicit type annotations
- Serialize ORM instances explicitly: `SchemaRead.model_validate(orm_instance)`
- Do not raise `HTTPException` — let domain exceptions propagate to app-level exception handlers (see Error responses)
- Use `async def` — this project uses async SQLAlchemy throughout

## Schemas (Pydantic)

- Use `Literal` types for constrained string values
- Naming: `<Resource>Create`, `<Resource>Update`, `<Resource>Read`
- Use `model_config = ConfigDict(from_attributes=True)` on Read models
- Do not use `RootModel` for wrapping single values

## Services

- Accept `AsyncSession` as first parameter
- Return ORM model instances (endpoint serializes via schema)
- Raise domain exceptions (not `HTTPException`) — endpoints catch and translate to HTTP status codes
- One service module per resource; group related operations

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

## Models package

Re-export all ORM model classes in `models/__init__.py` with `__all__`. This ensures Alembic autogenerate and the test conftest's `from a11y_health.models import *` discover all tables.

## Error responses

- Services raise domain exceptions (defined in `core/exceptions.py`)
- `main.py` maps exception classes to HTTP status codes in `_EXCEPTION_STATUS_CODES` and registers handlers in a loop — add new domain exceptions there
- Endpoints never catch or raise `HTTPException` directly
- Let FastAPI's built-in 422 handling cover validation errors
- Use 409 for domain conflicts, 404 for missing resources
