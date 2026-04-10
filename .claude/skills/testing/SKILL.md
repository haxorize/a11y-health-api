---
name: testing
description: Test conventions for this project. Use when writing tests, adding fixtures, or setting up test infrastructure.
---

# Testing Conventions

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

Five fixtures, layered:

- **`engine`** (session scope) — creates a test `AsyncEngine`, drops and recreates all tables once per session
- **`client`** — `AsyncClient` for endpoints that don't touch the DB
- **`db_session`** — `AsyncSession` wrapped in a rolled-back transaction for direct DB access (depends on `engine`)
- **`db_client`** — `AsyncClient` with `app.dependency_overrides[get_db]` set to use `db_session`; clears overrides in a `finally` block. For endpoints that touch the DB
- **`axe_payload`** (session scope) — loads `tests/fixtures/humana.com-home.json` as a dict; used by page result tests

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
- No docstrings on tests — the test name is the documentation. Use inline comments only when showing non-obvious context like formulas or math

## Writing service tests

Test services directly with `db_session` when you want to bypass HTTP:

```python
async def test_create_scan_service(db_session: AsyncSession) -> None:
    scan = await scan_service.create(db_session, url="https://example.com")
    assert scan.url == "https://example.com"
    assert scan.scan_id is not None
```

## Factory patterns

For test data setup, use simple async helper functions in `tests/factories.py` with explicit keyword arguments and defaults:

```python
async def make_org_unit(db: AsyncSession, *, name: str = "Test Org", parent_id: int | None = None) -> OrgUnit:
    org_unit = OrgUnit(name=name, parent_id=parent_id)
    db.add(org_unit)
    await db.flush()
    return org_unit
```

Call in tests: `org_unit = await make_org_unit(db_session, name="Humana")`

Factories use `await db.flush()` (not `commit()`) — this matches the service layer pattern and works within the transactional rollback isolation of `db_session`. When computing derived values (e.g., ratios, percentages), import and reuse production helpers (e.g., `safe_ratio` from `services/score.py`) rather than duplicating the formula inline.

For resources with required parent FK chains, add `make_<resource>_with_parents` composite helpers that create the full ancestry in one call:

```python
scan_run = await make_scan_run_with_parents(db_session, slug="my-app", status=ScanRunStatus.PENDING)
```

For building in-memory data structures (e.g., axe JSON payloads), use sync helpers that return plain dicts:

```python
def make_violation(rule_id: str, impact: str) -> dict[str, Any]:
    return {"id": rule_id, "impact": impact, ...}

def make_axe_payload(*, url: str = "https://example.com", violations: Any = None, incomplete: Any = None) -> dict[str, Any]:
    return {"testSubject": {"fileName": url}, "findings": {"violations": violations or [], ...}}
```

These don't touch the DB and don't need `async` or `flush()`.

## What to test at which layer

- **Endpoints**: HTTP status codes, response shape, auth/permission checks
- **Services**: business logic, edge cases, error conditions
- **Both**: use endpoint tests as integration tests; service tests for focused unit coverage

## Class-based test grouping

Group related tests into a class when testing facets of a single concept (e.g., scoring logic). No `__init__`, no fixtures on `self` — just a namespace:

```python
class TestPageHealthCategorization:
    async def test_critical_impact_lowers_health(self, db_session: AsyncSession) -> None:
        ...

    async def test_minor_impact_stays_healthy(self, db_session: AsyncSession) -> None:
        ...
```

Use flat `async def test_*` functions for standalone cases that don't benefit from grouping.

## Float comparisons

Use `pytest.approx` for float assertions (scores, percentages):
```python
from pytest import approx
assert score == approx(0.85)
```
