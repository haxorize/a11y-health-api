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
  test_config.py           # top-level Settings/config tests
  fixtures/                # sample axe JSON payloads and other static test data
  api/
    test_health.py          # tests for api/v1/endpoints/health.py
    test_<resource>.py      # one file per endpoint module
  services/
    test_<resource>.py      # direct service-layer tests
  schemas/
    test_<schema>.py        # Pydantic schema validation tests
  core/
    test_database.py        # tests for core/database.py helpers (Base, get_db, etc.)
  cli/
    test_<command>.py       # CLI tool tests (e.g., test_ingest.py, test_import.py)
```

## Fixtures (from conftest.py)

Five fixtures, layered:

- **`engine`** (session scope) — creates a test `AsyncEngine`, drops and recreates all tables once per session
- **`client`** — `AsyncClient` for endpoints that don't touch the DB
- **`db_session`** — `AsyncSession` wrapped in a rolled-back transaction for direct DB access (depends on `engine`)
- **`db_client`** — `AsyncClient` with `app.dependency_overrides[get_db]` set to use `db_session`; clears overrides in a `finally` block. For endpoints that touch the DB
- **`axe_payload`** (function scope) — loads `tests/fixtures/humana.com-home.json` as a dict; used by page result tests. Function scope prevents cross-test pollution from mutations

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

Factories use `await db.flush()` (not `commit()`) — this matches the service layer pattern and works within the transactional rollback isolation of `db_session`. When computing derived values (e.g., ratios, percentages), import and reuse production helpers (e.g., `safe_ratio` from `services/score_snapshot.py`) rather than duplicating the formula inline.

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

For factories that create many instances of the same resource, use a module-level `itertools.count()` sequence to generate unique defaults automatically:
```python
_brand_seq = itertools.count(1)

async def make_brand(db: AsyncSession, *, name: str | None = None) -> Brand:
    if name is None:
        name = f"Test Brand {next(_brand_seq)}"
    ...
```

For test assertions that query derived state (e.g., checking rollup snapshots), add query helpers to `factories.py`:
```python
async def latest_ou_snapshot(db: AsyncSession, org_unit_id: int) -> ScoreSnapshot:
    result = await db.execute(
        select(ScoreSnapshot).where(ScoreSnapshot.org_unit_id == org_unit_id)
        .order_by(ScoreSnapshot.id.desc()).limit(1)
    )
    return result.scalar_one()
```

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

## Markers

Declared in `pyproject.toml` under `[tool.pytest.ini_options]`:

- `slow` — tests that take noticeably longer; skip locally with `-m "not slow"`
- `integration` — end-to-end tests crossing multiple layers

`addopts = ["--strict-markers", "--strict-config"]` is on, so a typo'd marker fails the run. Add new markers to `pyproject.toml` before using them.

```python
@pytest.mark.slow
async def test_full_scan_ingestion(...) -> None: ...
```

## Mocking

Use the `mocker` fixture from `pytest-mock` rather than raw `unittest.mock` — it auto-cleans patches per test.

```python
async def test_cli_uploads_scan(mocker) -> None:
    post = mocker.patch("httpx.AsyncClient.post", new_callable=mocker.AsyncMock)
    post.return_value.status_code = 201
    await run_ingest(...)
    post.assert_awaited_once()
```

- Mock at the seam closest to the boundary (e.g., `httpx.AsyncClient.post`), not deep into your own code
- For async callables use `new_callable=mocker.AsyncMock` and assert with `assert_awaited_once`/`assert_awaited_with`
- Don't mock the database — the `db_session` rollback fixture is the canonical isolation mechanism

## Recipes

See [references/test-recipes.md](references/test-recipes.md) for coverage and runner-flag commands.

## Anti-patterns

- **Don't share mutable state across tests** — no module-level lists/dicts that tests append to. Use fixtures.
- **Don't test private/internal cache state** — assert on observable behavior, not `_internal_attr`.
- **Don't write monolithic "everything" fixtures** — small composable fixtures beat one mega-setup.
- **Don't over-specify mocks** — assert on the call shape that matters, not every kwarg.
- **Don't catch exceptions in tests** — use `pytest.raises(ExceptionType)`; bare `try/except` swallows real failures.
- **Don't let real network or DB calls leak into "unit" tests** — mock the seam or use the transactional `db_session`.
- **Don't `commit()` in tests or factories** — use `flush()`; `commit()` breaks the rollback isolation.
- **Don't `asyncio.sleep()` to wait for state** — poll the condition with a deadline (loop: check, short sleep, re-check, fail past timeout) and assert what you waited *for*; a fixed sleep is either too slow or flaky. Fixed sleeps are legitimate only when elapsed time is itself the behavior under test (e.g., TTL expiry).
