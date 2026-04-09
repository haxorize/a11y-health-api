---
name: testing
description: Test conventions for this project. Use when writing tests, adding fixtures, or setting up test infrastructure.
---

# Testing Conventions

## Running tests

```bash
uv run pytest              # all tests
uv run pytest tests/api/   # specific directory
uv run pytest -x           # stop on first failure
uv run pytest --cov=a11y_health  # with coverage
```

Config in `pyproject.toml`: `testpaths = ["tests"]`, `asyncio_mode = "auto"`.

## Test layout

Mirror the app structure:

```
tests/
  conftest.py              # shared fixtures (client, db_session, db_client)
  fixtures/                # sample axe JSON payloads and other static test data
  api/
    test_health.py          # tests for api/v1/endpoints/health.py
    test_<resource>.py      # one file per endpoint module
  services/
    test_<resource>.py      # direct service-layer tests
```

## Fixtures (from conftest.py)

Three fixtures, each for a different testing need:

- **`client`** — `AsyncClient` for endpoints that don't touch the DB
- **`db_session`** — `AsyncSession` wrapped in a rolled-back transaction for direct DB access
- **`db_client`** — `AsyncClient` with `get_db` overridden to use `db_session`; for endpoints that touch the DB

Every DB test uses transactional isolation — the transaction rolls back after each test, so no cleanup is needed.

## Writing endpoint tests

```python
async def test_create_scan(db_client: AsyncClient) -> None:
    response = await db_client.post("/api/v1/scans", json={"url": "https://example.com"})
    assert response.status_code == 201
    data = response.json()
    assert data["url"] == "https://example.com"
    assert "scan_id" in data
```

- Use `db_client` when the endpoint reads/writes the database
- Use `client` for stateless endpoints (e.g., health check)
- All test functions are `async def` (asyncio_mode is auto)
- Explicit return type annotation: `-> None`

## Writing service tests

Test services directly with `db_session` when you want to bypass HTTP:

```python
async def test_create_scan_service(db_session: AsyncSession) -> None:
    scan = await scan_service.create(db_session, url="https://example.com")
    assert scan.url == "https://example.com"
    assert scan.scan_id is not None
```

## Factory patterns

For test data setup, use simple async helper functions in `tests/factories.py`:

```python
async def make_scan(db: AsyncSession, **overrides) -> Scan:
    defaults = {"url": "https://example.com"}
    defaults.update(overrides)
    scan = Scan(**defaults)
    db.add(scan)
    await db.flush()
    return scan
```

Call in tests: `scan = await make_scan(db_session, url="https://other.com")`

## What to test at which layer

- **Endpoints**: HTTP status codes, response shape, auth/permission checks
- **Services**: business logic, edge cases, error conditions
- **Both**: use endpoint tests as integration tests; service tests for focused unit coverage
