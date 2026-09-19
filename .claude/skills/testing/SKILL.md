---
name: testing
description: Test conventions for this project — layout, the six conftest fixtures, factories and arrange helpers, markers, and mocking. Use when writing or moving a test, adding a fixture, reaching for a factory, deciding where a new test file goes, or setting up test infrastructure.
---

# Testing Conventions

## Test layout

Mirror the app structure — except for a **suite-wide mechanism** or a **topology guard**, which live at the root beside their implementation rather than under the package they happen to guard. A mechanism enforces an invariant across the whole suite (Declaration Honesty, import honesty), or over a tracked artifact no package owns (`skills-sync.lock`, the prose documents), and has no single mirrored home. A topology guard reads the source tree — which module imports which, what reaches what — rather than exercising a module's behavior, so it sits at the root even when the rule it holds is scoped to one package. Filing either under a mirrored directory is what produced the mixed contract suite #133 had to split.

```
tests/
  __init__.py              # one in every test directory except fixtures/, which holds data
  conftest.py              # shared fixtures (engine, client, db_session, db_client, committed_session_factory, axe_payload)
  test_config.py           # top-level Settings/config tests
  _declaration_honesty.py  # the ADR 0033 mechanism; conftest wires it suite-wide
  test_declaration_honesty.py  # its own suite — canaries, include-level, enumeration
  import_graph.py          # shared import-reading helpers for the topology guards
  test_import_graph.py     # the shared walk's own coverage, pinned on a non-empty set
  test_import_honesty.py   # the ADR 0038 private-module rule, checked repo-wide
  test_sibling_imports.py  # sibling-import rules: which modules may import which siblings — services/ today
  test_shared_skill_lock.py  # each shared skill copy matches its hash in skills-sync.lock (ADR 0001)
  test_reachability.py     # every source module is reached from an entry point (ADR 0039)
  test_workflow_parity.py  # CI's lint steps vs `make lint`, and the three uv setup steps agreeing
  test_staged_worktree.py  # ADR 0046's two claims, over a scratch repo: the checkout is the
                           # staged tree, and neither the working tree nor the index moves
  _non_test_database.py    # refuses any connection the suite opens to DATABASE_URL's database
  test_non_test_database.py  # its own suite: the rule, and that conftest armed it
  test_prose_shape.py      # the six prose guards: code-prose wrap (the half W505 can't see), one-line
                           # markdown blocks (ADR 0040), American spelling (ADR 0041), the DOMAIN.md
                           # definition word ceiling (ADR 0018), the docs/architecture.md word band and
                           # em-dash cap (#148), and the 15,000-byte bound on every skill body
  factories.py             # the data factories, arrange helpers, and query helpers every suite shares
  fixtures/                # one sample Axe Payload (humana.com-home.json)
  api/
    test_health.py          # tests for api/v1/endpoints/health.py
    test_<router>.py        # one file per router, not per endpoint module — scan_runs.py declares
                            # three. Its two scan-run routers share test_scan_runs.py; pages_router
                            # is test_pages.py; a nested read takes its own file
                            # (test_scan_run_pages.py, test_scan_run_summary.py)
    test_rollup_deadlock.py # the #104 deadlock 409 through the full request stack; `integration`
  services/
    test_<resource>.py      # direct service-layer tests, one per public services/ module. The
                            # underscore-prefixed ones (_latest_snapshot, _org_subtree) have no
                            # file: they are exercised through the module that consumes them
    test_finding_persistence.py   # what one Axe Payload leaves behind across the finding tables
    test_rollup_serialization.py  # per-Owner Rollup on two sessions (#101, ADR 0029); `integration`
  schemas/
    test_<schema>.py        # Pydantic schema validation tests
  models/
    test_<model>.py         # model-level tests (defaults, constraints as declared)
  core/
    test_<module>.py        # one per core module that has one. error_body.py and exceptions.py
                            # have none — both are reached only through consumers, error_body
                            # through test_error_contract.py and cli/test_client.py's error decode
  cli/
    conftest.py             # CLI-only fixtures (no_server, live_server, socket_client, forwarded) — see references/cli-and-migration-tests.md
    test_<command>.py       # one file per command (test_ingest.py, test_import.py, test_org_units.py,
                            # test_brands.py)
    test_client.py          # transport, error decode, and timeouts over httpx.MockTransport
    test_live_server.py     # the CLI over a real socket (production AsyncHTTPTransport)
    test_terminal.py        # argv dispatch and the operator-facing ERROR line + exit code
  migrations/
    test_downgrade_floor.py # the floor is a real revision and never the head; reads the Makefile
    test_<revision>.py      # migration bodies through harness.py — see references/cli-and-migration-tests.md
```

## Fixtures (from conftest.py)

Six fixtures, layered:

- **`engine`** (session scope) — creates a database per run (`TEST_DATABASE_URL`'s name plus the pid), builds the schema in it, drops it at teardown. Two runs never share one, so the hook's suite and yours cannot drop tables under each other. Every connection sets `deadlock_timeout = 50ms` so deadlock-provoking tests detect in milliseconds instead of idling out Postgres's 1s default — don't re-set the GUC per test. Its superuser requirement and the one sanctioned per-session exception are in [references/cli-and-migration-tests.md](references/cli-and-migration-tests.md)
- **`client`** — `AsyncClient` for endpoints that don't touch the DB
- **`db_session`** — `AsyncSession` wrapped in a rolled-back transaction for direct DB access (depends on `engine`)
- **`db_client`** — `AsyncClient` with `app.dependency_overrides[get_db]` set to use `db_session`; clears overrides in a `finally` block. For endpoints that touch the DB. The override yields the session and stops there, where production's `get_db` commits on success and rolls back on an exception — so a row a handler flushed before raising a 4xx stays visible for the rest of the test, where production would have discarded it. That is a fidelity limit to test around, not a bug: ADR 0011's rollback isolation, below, is why the override is shaped this way. Assert the rejection itself — a follow-up read through `db_client` cannot tell you what production kept
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
- Test functions are `async def` (asyncio_mode is auto). A test that touches neither the app's event loop nor the database stays `def` — `tests/api/test_findings.py::test_openapi_declares_typed_classification_schema` reads the generated schema straight off `app.openapi()`
- Explicit return type annotation: `-> None`
- No docstrings on test *functions* — the test name is the documentation. Use inline comments only when showing non-obvious context like formulas or math
- A test *module* earns a header on the same criterion as a source module: its purpose is not evident from its path and a glance ([ADR 0018](../../../docs/adr/0018-documentation-strategy-prose-over-docstrings.md), 2026-09-05 amendment). The topology guards, the migration-body suites, and the two-session and real-socket files carry one; a suite that mirrors a CRUD module does not

## Writing service tests

Test services directly with `db_session` when you want to bypass HTTP:

```python
async def test_create_scan_service(db_session: AsyncSession) -> None:
    scan = await scan_service.create(db_session, url="https://example.com")
    assert scan.url == "https://example.com"
    assert scan.scan_id is not None
```

## Arrange with a factory, compute the expectation yourself

Arrange side: reach for `tests/factories.py` and reuse production code freely — a factory that calls the real service to set a row up is arranging, not asserting. Writing one is [references/factories.md](references/factories.md).

Expected side: no production helper. Importing `safe_ratio` from `services/score_snapshot.py` to build the number you compare against asserts the formula against itself, and the test stays green when the formula is wrong. Write the expected value as a literal, with the arithmetic in an inline comment.

## What to test at which layer

A domain rule is asserted at exactly one seam — the service interface, where every entry path (HTTP, CLI, scoring orchestration) converges. See [ADR 0021](../../../docs/adr/0021-domain-rules-test-once-at-the-service-seam.md) for the rationale.

- **Services** (`tests/services/`): the single home of domain rules — create/update/delete rules, filters, existence errors, lifecycle triggers. Assert error modes as exception types (`pytest.raises(NotFoundError)`), not status codes.
- **Endpoints** (`tests/api/`): transport translation only, chosen positively per file — one representative round-trip per operation, every distinct status-code path the operation can produce, and assertions only transport can make (response serialization, query-parameter decoding). Never "the service test again, over HTTP."
- **Never both.** Before adding an endpoint test, check whether a service test already asserts the rule; if it does, the endpoint test is justified only by one of the transport slots above. Before removing a duplicated endpoint test, twin-verify: confirm a service test asserts the same rule, and move any assertion unique to the endpoint twin (a status-code path, a serialized shape) into the surviving layer first — never remove by name-match alone.

## Class-based test grouping

Group related tests into a class when testing facets of a single concept (e.g., scoring logic). No `__init__`, no fixtures on `self` — just a namespace:

```python
class TestPageHealthCategorization:
    async def test_critical_impact_lowers_health(self, db_session: AsyncSession) -> None: ...

    async def test_minor_impact_stays_healthy(self, db_session: AsyncSession) -> None: ...
```

Use flat `async def test_*` functions for standalone cases that don't benefit from grouping.

## Float comparisons

Use `pytest.approx` for float assertions (scores, percentages):
```python
from pytest import approx

assert score == approx(0.85)
```

The one exception is a test whose property *is* bitwise reproducibility — the rollup recompute landing on the stored value so the no-change skip holds. There, exact `==` is the assertion, and `approx` would make it vacuous.

## Markers

Declared in `pyproject.toml` under `[tool.pytest.ini_options]`:

- `integration` — end-to-end tests crossing multiple layers; opt out with `-m "not integration"`

`addopts = ["--strict-markers", "--strict-config"]` is on, so a typo'd marker fails the run. Add new markers to `pyproject.toml` before using them.

An integration file is marked whole, not per function — three carry it (`tests/api/test_rollup_deadlock.py`, `tests/services/test_rollup_serialization.py`, `tests/cli/test_live_server.py`):

```python
pytestmark = pytest.mark.integration
```

## References

- [references/factories.md](references/factories.md) — open before adding or changing a helper in `tests/factories.py`: naming, parent-chain composites, sequenced defaults, the shared scoring arrange helpers, and query helpers. Calling an existing factory needs nothing from it
- [references/test-recipes.md](references/test-recipes.md) — open when you want a coverage report or a runner flag
- [references/cli-and-migration-tests.md](references/cli-and-migration-tests.md) — open before writing a CLI test, a migration-body test, or a session-scoped fixture that swaps an attribute
- [references/mocking.md](references/mocking.md) — open before mocking: `mocker` over raw `unittest.mock`, `monkeypatch` for a swap that asserts nothing, and the transport as the seam for anything leaving the process

## Anti-patterns

- **Don't `commit()` in tests or factories** — use `flush()`; `commit()` breaks the rollback isolation. (Sessions from `committed_session_factory` are the exception — committing is their purpose, and its truncate teardown cleans up.)
- **Don't make parallel HTTP calls in a single test** — `db_client` routes every request through one shared `AsyncSession`, which isn't concurrent-safe; `asyncio.gather` on it deadlocks or corrupts state. Await calls sequentially.
- **Don't `asyncio.sleep()` to wait for state** — poll the condition with a deadline (loop: check, short sleep, re-check, fail past timeout) and assert what you waited *for*; a fixed sleep is either too slow or flaky. Fixed sleeps are legitimate only when elapsed time is itself the behavior under test (e.g., TTL expiry).
