---
name: testing
description: Test conventions for this project — layout, the nine conftest fixtures, factories and arrange helpers, markers, and mocking. Use when writing or moving a test, adding a fixture, reaching for a factory, deciding where a new test file goes, or setting up test infrastructure.
---

# Testing Conventions

## Test layout

Mirror the app structure — except for a **suite-wide mechanism**, a **topology guard**, an **app-wide contract sweep**, a **test of something outside `src/`**, or **test data two mirrored suites share**, which live at the root beside their implementation rather than under the package they guard. A mechanism enforces an invariant across the whole suite (Declaration Honesty, import honesty), or over a tracked artifact no package owns (`skills-sync.lock`, the prose documents), and has no single mirrored home. A topology guard reads the source tree — which module imports which, what reaches what — rather than exercising a module's behavior, so it sits at the root even when the rule it holds is scoped to one package. Filing either of those two under a mirrored directory is what produced the mixed contract suite #133 had to split. A test of something outside `src/` — a script under `scripts/`, the way `test_staged_worktree.py` drives `scripts/staged_worktree.sh` — has no package to mirror at all. An app-wide contract sweep checks a rule over every served operation, as `test_cursor_pagination.py` does and `test_main.py`'s operation-id check did first, so no one package owns it.

```
tests/
  __init__.py              # one in every test directory except fixtures/, which holds data
  conftest.py              # the shared fixtures, listed under Fixtures below
  test_config.py           # top-level Settings/config tests
  test_main.py             # application assembly: operation-id uniqueness, CORS by allowed origins, lifespan
  _declaration_honesty.py  # the ADR 0033 mechanism; conftest wires it suite-wide
  test_declaration_honesty.py  # its own suite — canaries, include-level, enumeration
  test_cursor_pagination.py  # the Cursor Pagination conformance sweep over every served operation
  import_graph.py          # shared import-reading helpers for the topology guards
  test_import_graph.py     # the shared walk's own coverage, pinned on a non-empty set
  test_import_honesty.py   # the ADR 0038 private-module rule, checked repo-wide
  test_sibling_imports.py  # sibling-import rules: which modules may import which siblings — services/ today
  test_forbidden_edges.py  # package import edges that must not exist
  test_architecture_citations.py  # cited docs/architecture.md headings exist
  test_shared_skill_lock.py  # each shared skill copy matches its hash in skills-sync.lock (ADR 0001)
  test_reachability.py     # every source module is reached from an entry point (ADR 0039)
  test_workflow_parity.py  # CI's lint steps vs `make lint`
  test_staged_worktree.py  # ADR 0046's two claims, over a scratch repo: the checkout is the
                           # staged tree, and neither the working tree nor the index moves
  _non_test_database.py    # refuses any connection the suite opens to DATABASE_URL's database
  test_non_test_database.py  # its own suite: the rule, and that conftest armed it
  test_prose_shape.py      # the six prose guards, the 15,000-byte bound on every skill body and
                           # reference among them; the code-documentation skill names each
  factories.py             # the data factories, arrange helpers, and query helpers every suite shares
  finding_filter_cases.py  # the findings filter case table the API and service suites both read
  test_factories.py        # the Latest Score Snapshot readers
  test_truncate_teardown.py  # teardown lock timeout
  fixtures/                # one sample Axe Payload (humana.com-home.json)
  api/, services/, schemas/, models/, core/, cli/, migrations/  # mirrored: references/layout.md
```

## Fixtures (from conftest.py)

Nine fixtures, layered:

- **`engine`** (session scope) — creates a database per run (`TEST_DATABASE_URL`'s name plus the pid), builds the schema in it, drops it at teardown. Two runs never share one, so the hook's suite and yours cannot drop tables under each other. Every connection sets `deadlock_timeout = 50ms` so deadlock-provoking tests detect in milliseconds instead of idling out Postgres's 1s default — don't re-set the GUC per test. Its superuser requirement and the one sanctioned exception are in [references/cli-and-migration-tests.md](references/cli-and-migration-tests.md)
- **`roundtrip`** / **`migrated_database_url`** (session scope) — the migration roundtrip's result, and its database's URL once it succeeded
- **`client`** — `AsyncClient` for endpoints that don't touch the DB
- **`db_session`** — `AsyncSession` wrapped in a rolled-back transaction for direct DB access (depends on `engine`)
- **`db_client`** — `AsyncClient` with the session source bound, through `bind_session_source`, to one that hands every request `db_session`; the binding is restored on exit. For endpoints that touch the DB. It never commits or rolls back per request as production's `get_db` does — see [references/fixtures.md](references/fixtures.md) before asserting on state after a 4xx
- **`committed_session_factory`** — factory for real-commit sessions on separate connections, for the rare test that needs one session's writes visible to another (genuine lock contention); teardown truncates every table. A test that also sends requests through `client` binds `SessionSource(engine)` with `bind_session_source`, as `test_rollup_deadlock.py` does; unbound, the non-test-database guard refuses them. The sanctioned exception to rollback isolation — see [ADR 0011](../../../docs/adr/0011-transactional-rollback-test-isolation.md)
- **`axe_payload`** (function scope) — `tests/fixtures/humana.com-home.json`, parsed once per run; each test gets its own copy
- **`source_edges`** (session scope) — `package_edges` over `src/`, walked once per run

Every DB test uses transactional isolation — each test's transaction rolls back, so no cleanup is needed. The one exception is `committed_session_factory` (above).

## Writing endpoint tests

```python
async def test_create_org_unit(db_client: AsyncClient) -> None:
    response = await db_client.post("/api/v1/org-units", json={"name": "Digital"})
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Digital"
    assert data["parent_id"] is None
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
async def test_create_org_unit_service(db_session: AsyncSession) -> None:
    org_unit = await org_unit_service.create_org_unit(db_session, OrgUnitCreate(name="Digital"))
    assert org_unit.name == "Digital"
    assert org_unit.id is not None
```

## Arrange with a factory, compute the expectation yourself

Arrange side: reach for `tests/factories.py` and reuse production code freely — a factory that calls the real service to set a row up is arranging, not asserting. Writing one is [references/factories.md](references/factories.md).

Expected side: no production helper. Calling the scoring arithmetic to build the number you compare against asserts the formula against itself, and the test stays green when the formula is wrong. Write the expected value as a literal, with the arithmetic in an inline comment.

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

An integration file is marked whole, not per function — four carry it (`tests/api/test_rollup_deadlock.py`, `tests/services/test_rollup_serialization.py`, `tests/services/test_org_unit_reparent_race.py`, `tests/cli/test_live_server.py`):

```python
pytestmark = pytest.mark.integration
```

## References

- [references/factories.md](references/factories.md) — open before adding or changing a helper in `tests/factories.py`: naming, parent-chain composites, sequenced defaults, the shared scoring arrange helpers, and query helpers. Calling an existing factory needs nothing from it
- [references/layout.md](references/layout.md) — open before adding a file under a mirrored test directory: what each one holds
- [references/test-recipes.md](references/test-recipes.md) — open when you want a coverage report or a runner flag
- [references/cli-and-migration-tests.md](references/cli-and-migration-tests.md) — open before writing a CLI test, a migration-body test, or a session-scoped fixture that swaps an attribute
- [references/fixtures.md](references/fixtures.md) — open before asserting on state a rejected `db_client` request left behind
- [references/mocking.md](references/mocking.md) — open before mocking: `mocker` over raw `unittest.mock`, `monkeypatch` for a swap that asserts nothing, and the transport as the seam for anything leaving the process

## Anti-patterns

- **Don't `commit()` in tests or factories** — use `flush()`; `commit()` breaks the rollback isolation. (`committed_session_factory` sessions are the exception, above.)
- **Don't make parallel HTTP calls in a single test** — `db_client` routes every request through one shared `AsyncSession`, which isn't concurrent-safe; `asyncio.gather` on it deadlocks or corrupts state. Await calls sequentially.
- **Don't `asyncio.sleep()` to wait for state** — poll the condition with a deadline (loop: check, short sleep, re-check, fail past timeout) and assert what you waited *for*; a fixed sleep is either too slow or flaky. Fixed sleeps are legitimate only when elapsed time is itself the behavior under test (e.g., TTL expiry).
