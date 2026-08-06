---
name: testing
description: Test conventions for this project. Use when writing tests, adding fixtures, or setting up test infrastructure.
---

# Testing Conventions

## Test layout

Mirror the app structure — except for a **suite-wide mechanism**, which lives
at the root beside its implementation rather than under the package it happens
to guard. A mechanism enforces an invariant across the whole suite (Declaration
Honesty, import honesty) and has no single mirrored home; filing it under a
mirrored directory is what produced the mixed contract suite #133 had to split.

```
tests/
  conftest.py              # shared fixtures (client, db_session, db_client, committed_session_factory)
  test_config.py           # top-level Settings/config tests
  _declaration_honesty.py  # the ADR 0033 mechanism; conftest wires it suite-wide
  test_declaration_honesty.py  # its own suite — canaries, include-level, enumeration
  import_graph.py          # shared import-reading helpers for the topology guards
  test_import_honesty.py   # the ADR 0038 private-module rule, checked repo-wide
  test_prose_shape.py      # comments and docstrings wrap whole; the half W505 can't see
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
    conftest.py             # `no_server`: a client that fails the test if anything reaches the transport
    test_<command>.py       # one file per command (test_ingest.py, test_import.py, test_org_units.py)
    test_client.py          # transport, error decode, and timeouts over httpx.MockTransport
    test_terminal.py        # argv dispatch and the operator-facing ERROR line + exit code
  migrations/
    test_<revision>.py      # migration-body tests: run a shipped upgrade()/downgrade() bound to db_session; restore pre-migration schema via the shipped downgrade — hand-written DDL only when the needed downgrade is irreversible, with the reason stated in place (harness.py; upgrade usage: test_rederive_app_slugs.py; downgrade restore: test_single_root_org_unit_index.py)
```

## Fixtures (from conftest.py)

Six fixtures, layered:

- **`engine`** (session scope) — creates a test `AsyncEngine`, drops and recreates all tables once per session. Every connection sets `deadlock_timeout = 50ms` so deadlock-provoking tests detect in milliseconds instead of idling out Postgres's 1s default — don't re-set the GUC per test (raise it per session only to steer which backend is the victim, as `test_rollup_deadlock.py` does). The GUC is superuser-set: dev and CI connect as superuser, and because it rides the connection startup packet, a non-superuser test role fails **every** connection with `FATAL: permission denied to set parameter` — the escape hatch is `GRANT SET ON PARAMETER deadlock_timeout TO <role>`
- **`client`** — `AsyncClient` for endpoints that don't touch the DB
- **`db_session`** — `AsyncSession` wrapped in a rolled-back transaction for direct DB access (depends on `engine`)
- **`db_client`** — `AsyncClient` with `app.dependency_overrides[get_db]` set to use `db_session`; clears overrides in a `finally` block. For endpoints that touch the DB
- **`committed_session_factory`** — factory for real-commit sessions on separate connections, for the rare test that needs one session's writes visible to another (genuine lock contention); teardown truncates every table. The sanctioned exception to rollback isolation — see [ADR 0011](../../../docs/adr/0011-transactional-rollback-test-isolation.md)
- **`axe_payload`** (function scope) — loads `tests/fixtures/humana.com-home.json` as a dict; used by page result tests. Function scope prevents cross-test pollution from mutations

Every DB test uses transactional isolation — the transaction rolls back after each test, so no cleanup is needed. The one exception is tests built on `committed_session_factory`, which really commit and rely on its truncate teardown.

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

When computing derived values (e.g., ratios, percentages), import and reuse production helpers (e.g., `safe_ratio` from `services/score_snapshot.py`) rather than duplicating the formula inline.

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

A domain rule is asserted at exactly one seam — the service interface, where every entry path (HTTP, CLI, scoring orchestration) converges. See [ADR 0021](../../../docs/adr/0021-domain-rules-test-once-at-the-service-seam.md) for the rationale.

- **Services** (`tests/services/`): the single home of domain rules — create/update/delete rules, filters, existence errors, lifecycle triggers. Assert error modes as exception types (`pytest.raises(NotFoundError)`), not status codes.
- **Endpoints** (`tests/api/`): transport translation only, chosen positively per file — one representative round-trip per operation, every distinct status-code path the operation can produce, and assertions only transport can make (response serialization, query-parameter decoding). Never "the service test again, over HTTP."
- **Never both.** Before adding an endpoint test, check whether a service test already asserts the rule; if it does, the endpoint test is justified only by one of the transport slots above. Before removing a duplicated endpoint test, twin-verify: confirm a service test asserts the same rule, and move any assertion unique to the endpoint twin (a status-code path, a serialized shape) into the surviving layer first — never remove by name-match alone.

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

- **Don't `commit()` in tests or factories** — use `flush()`; `commit()` breaks the rollback isolation. (Sessions from `committed_session_factory` are the exception — committing is their purpose, and its truncate teardown cleans up.)
- **Don't make parallel HTTP calls in a single test** — `db_client` routes every request through one shared `AsyncSession`, which isn't concurrent-safe; `asyncio.gather` on it deadlocks or corrupts state. Await calls sequentially.
- **Don't `asyncio.sleep()` to wait for state** — poll the condition with a deadline (loop: check, short sleep, re-check, fail past timeout) and assert what you waited *for*; a fixed sleep is either too slow or flaky. Fixed sleeps are legitimate only when elapsed time is itself the behavior under test (e.g., TTL expiry).
