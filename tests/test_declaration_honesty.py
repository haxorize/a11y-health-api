import ast
import inspect
from collections.abc import Mapping
from types import SimpleNamespace

import pytest
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.error_contract import (
    ErrorCode,
    error_responses,
    register_error_handlers,
)
from a11y_health.core.exceptions import NotFoundError
from a11y_health.models.app import App
from a11y_health.services import owner, scoring_orchestration
from tests._declaration_honesty import (
    DeclarationHonestyShim,
    _operations_declaring,
    _request_scope,
    observation_scope,
    record_observation,
    run_was_narrowed,
    stale_rollup_declaration_message,
)
from tests.factories import (
    assert_error,
    make_app_with_org_unit,
    make_org_unit,
    make_page_result,
    make_scan_run_with_parents,
)
from tests.import_graph import Module, source_paths_importing

_AN_APP = App(org_unit_id=1, brand_id=1)


# Rollup-race 409s never fire organically in endpoint tests, so the
# Declaration Honesty shim can't catch a missing concurrent_rollup declaration
# at the response; the instrumentation asserts it at the raise site instead, on
# every rollup any test provokes over HTTP (#113). Passthrough outside a
# request context is proven organically by the service-layer suite, which calls
# the wrapped rollup functions directly.
async def test_rollup_from_operation_without_declared_concurrent_rollup_fails() -> None:
    route = SimpleNamespace(path="/widgets/{widget_id}", responses=error_responses(ErrorCode.NOT_FOUND))
    scope = {"method": "PATCH", "path": "/api/v1/widgets/1", "route": route}
    with _request_scope(scope), pytest.raises(AssertionError, match="concurrent_rollup"):
        # session=None proves the check fires before any rollup work runs.
        await scoring_orchestration.on_app_latest_snapshot_changed(None, _AN_APP)  # ty: ignore[invalid-argument-type]


def _from_imports_a_rollup_raiser(imports: set[str]) -> bool:
    # Derived from the module the instrumentation actually patches, so moving
    # the Owner Dispatcher moves the pin with it rather than leaving it
    # scanning for a path that no longer exists and passing vacuously.
    prefix = f"{owner.__name__}."
    return any(name.startswith(prefix) and "rollup" in name.removeprefix(prefix) for name in imports)


def test_no_src_caller_binds_a_rollup_raiser_by_from_import(source_edges: Mapping[Module, frozenset[str]]) -> None:
    # The instrumentation patches owner module attributes, so it only
    # intercepts attribute-access call sites; a `from ...owner import
    # rollup*` binding taken at import time would bypass enforcement entirely
    # (ADR 0033). This pins the calling convention the mechanism depends on.
    # The walk resolves relative spellings and cannot be tripped by a comment
    # that merely quotes the forbidden import.
    import a11y_health

    offenders = source_paths_importing(source_edges, a11y_health, _from_imports_a_rollup_raiser)
    assert not offenders, f"rollup raisers must be called as owner attributes, not from-imported: {offenders}"


_RAISE_PATH = frozenset({"_concurrent_rollup_error", "ConcurrentRollupError"})


def _rollup_raisers(source: str) -> set[str]:
    """The public module-level functions in `source` that reach the rollup
    raise path, directly or through other functions in the same module."""
    functions = {
        node.name: {name.id for name in ast.walk(node) if isinstance(name, ast.Name)}
        for node in ast.parse(source).body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    reaching = {name for name, names in functions.items() if names & _RAISE_PATH}
    while grown := {name for name, names in functions.items() if names & reaching} - reaching:
        reaching |= grown
    return {name for name in reaching if not name.startswith("_")}


class TestRollupRaiserNaming:
    # The instrumentation wraps only `rollup*` names on the Owner Dispatcher,
    # so a public function reaching the rollup raise path under another name
    # is instrumented by nothing (ADR 0033 residual). Walking the call graph
    # inside the module finds every such function.
    def test_a_public_function_reaching_the_raise_path_under_another_name_is_reported(self) -> None:
        source = (
            "def _concurrent_rollup_error(owner_type, owner_id): ...\n"
            "async def _apply_rollup(session):\n"
            "    raise _concurrent_rollup_error(1, 2)\n"
            "async def rollup(session):\n"
            "    await _apply_rollup(session)\n"
            "async def recompute_ancestors(session):\n"
            "    await _apply_rollup(session)\n"
            "async def list_scores(session): ...\n"
        )

        assert _rollup_raisers(source) == {"rollup", "recompute_ancestors"}

    def test_a_direct_raise_of_the_error_class_is_the_raise_path_too(self) -> None:
        source = "def refresh():\n    raise ConcurrentRollupError(Owner, 1)\n"

        assert _rollup_raisers(source) == {"refresh"}

    def test_every_public_raiser_on_the_owner_dispatcher_carries_the_convention(self) -> None:
        raisers = _rollup_raisers(inspect.getsource(owner))
        assert "rollup" in raisers, "the call-graph walk found no raiser — it is not reading the raise path"

        assert sorted(name for name in raisers if not name.startswith("rollup")) == []


# Enforcement depth is the suite's coverage of rollup-triggering variants, so
# each known rollup-triggering operation gets an explicit canary driving its
# triggering variant over HTTP — the observation scope clears the key first, so
# it proves this test's own request was observed, not an earlier test's. A
# canary fails if the variant stops triggering rollups (coverage lost) or, via
# the raise-site assert, if the operation drops its concurrent_rollup
# declaration.
class TestRollupObservationCanaries:
    # Keys use the matched route's own template — the app's include mode
    # doesn't expose the /api/v1 mount prefix to the route object at handler
    # time.
    async def test_app_delete(self, db_client: AsyncClient, db_session: AsyncSession) -> None:
        app_row = await make_app_with_org_unit(db_session, slug="canary-app-delete")
        key = ("DELETE", "/apps/{app_id}")
        with observation_scope(key) as observation:
            response = await db_client.delete(f"/api/v1/apps/{app_row.id}")

        assert response.status_code == 204
        assert observation.observed

    async def test_app_reassignment(self, db_client: AsyncClient, db_session: AsyncSession) -> None:
        app_row = await make_app_with_org_unit(db_session, slug="canary-app-reassign")
        target = await make_org_unit(db_session, name="Canary Target", parent_id=app_row.org_unit_id)
        key = ("PATCH", "/apps/{app_id}")
        with observation_scope(key) as observation:
            response = await db_client.patch(f"/api/v1/apps/{app_row.id}", json={"org_unit_id": target.id})

        assert response.status_code == 200
        assert observation.observed

    async def test_org_unit_reparenting(self, db_client: AsyncClient, db_session: AsyncSession) -> None:
        root = await make_org_unit(db_session, name="Canary Root")
        new_parent = await make_org_unit(db_session, name="Canary Parent", parent_id=root.id)
        child = await make_org_unit(db_session, name="Canary Child", parent_id=root.id)
        key = ("PATCH", "/org-units/{org_unit_id}")
        with observation_scope(key) as observation:
            response = await db_client.patch(f"/api/v1/org-units/{child.id}", json={"parent_id": new_parent.id})

        assert response.status_code == 200
        assert observation.observed

    async def test_scan_run_completion(self, db_client: AsyncClient, db_session: AsyncSession) -> None:
        scan_run = await make_scan_run_with_parents(db_session, slug="canary-run-complete")
        await make_page_result(db_session, scan_run_id=scan_run.id)
        key = ("PATCH", "/scan-runs/{scan_run_id}")
        with observation_scope(key) as observation:
            response = await db_client.patch(f"/api/v1/scan-runs/{scan_run.id}", json={"status": "completed"})

        assert response.status_code == 200
        assert observation.observed

    async def test_scan_run_delete(self, db_client: AsyncClient, db_session: AsyncSession) -> None:
        scan_run = await make_scan_run_with_parents(db_session, slug="canary-run-delete")
        key = ("DELETE", "/scan-runs/{scan_run_id}")
        with observation_scope(key) as observation:
            response = await db_client.delete(f"/api/v1/scan-runs/{scan_run.id}")

        assert response.status_code == 204
        assert observation.observed


def _not_found_raising_app(include_responses: dict[int | str, dict[str, object]] | None) -> FastAPI:
    widget_app = FastAPI()
    register_error_handlers(widget_app)
    router = APIRouter()

    @router.get("/widgets/{widget_id}")
    async def get_widget(widget_id: int) -> None:
        raise NotFoundError(App, widget_id)

    widget_app.include_router(router, prefix="/api/v1", responses=include_responses)
    return widget_app


async def _get_widget_through_shim(widget_app: FastAPI) -> Response:
    transport = ASGITransport(app=DeclarationHonestyShim(widget_app))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get("/api/v1/widgets/1")


class TestIncludeLevelDeclarations:
    # FastAPI's non-copying include keeps include_router(responses=...)
    # declarations off the matched route object, so Declaration Honesty must
    # read the effective merged view, not route.responses (#120).
    async def test_mode_declared_only_at_include_level_is_honest(self) -> None:
        widget_app = _not_found_raising_app(error_responses(ErrorCode.NOT_FOUND))

        response = await _get_widget_through_shim(widget_app)
        assert_error(response, 404, "not_found")

    async def test_raisable_mode_declared_only_at_include_level_is_honest(self) -> None:
        widget_app = FastAPI()
        router = APIRouter()

        @router.patch("/widgets/{widget_id}")
        async def patch_widget(widget_id: int) -> None: ...

        widget_app.include_router(router, prefix="/api/v1", responses=error_responses(ErrorCode.CONCURRENT_ROLLUP))
        scope = {"method": "PATCH", "path": "/api/v1/widgets/1", "route": router.routes[0], "app": widget_app}
        # The raise-site assert must pass; the session=None crash that follows
        # proves the rollup itself was reached (contrast the undeclared test
        # below, which never gets past the assert).
        with (
            observation_scope(("PATCH", "/widgets/{widget_id}"), synthetic=True),
            _request_scope(scope),
            pytest.raises(AttributeError),
        ):
            await scoring_orchestration.on_app_latest_snapshot_changed(None, _AN_APP)  # ty: ignore[invalid-argument-type]

    async def test_undeclared_mode_behind_include_still_fails(self) -> None:
        widget_app = _not_found_raising_app(None)

        with pytest.raises(AssertionError, match="not declared"):
            await _get_widget_through_shim(widget_app)


class TestObservationScope:
    # The observed set feeds the session-finish stale diff, so a synthetic
    # observation that outlives its test masks a same-keyed stale declaration.
    # Dropping the scope's restore reds the first case.
    def test_a_synthetic_observation_does_not_outlive_its_scope(self) -> None:
        widget_app = _not_found_raising_app(error_responses(ErrorCode.CONCURRENT_ROLLUP))
        key = ("GET", "/widgets/{widget_id}")

        with observation_scope(key, synthetic=True):
            record_observation(key)

        assert stale_rollup_declaration_message(widget_app) is not None

    def test_a_real_observation_is_kept(self) -> None:
        widget_app = _not_found_raising_app(error_responses(ErrorCode.CONCURRENT_ROLLUP))
        key = ("GET", "/widgets/{widget_id}")

        try:
            with observation_scope(key) as observation:
                record_observation(key)
            assert observation.observed
            assert stale_rollup_declaration_message(widget_app) is None
        finally:
            with observation_scope(key, synthetic=True):
                pass

    def test_a_scope_that_observes_nothing_leaves_an_earlier_observation_standing(self) -> None:
        # A canary whose request stops reaching the rollup fails on its own;
        # it must not also erase what an earlier test observed.
        widget_app = _not_found_raising_app(error_responses(ErrorCode.CONCURRENT_ROLLUP))
        key = ("GET", "/widgets/{widget_id}")

        with observation_scope(key, synthetic=True):
            record_observation(key)
            with observation_scope(key) as observation:
                pass
            assert not observation.observed
            assert stale_rollup_declaration_message(widget_app) is None


class _Options:
    def __init__(self, **values: object) -> None:
        self._values = values

    def getoption(self, name: str) -> object:
        return self._values.get(name)


class TestRunWasNarrowed:
    # The gate diffs only after a complete run; each narrowing on its own
    # skips it, and a plain run with tests executed does not.
    def test_a_complete_run_is_not_narrowed(self) -> None:
        assert not run_was_narrowed(_Options(file_or_dir=[]), deselected=False, tests_ran=3)

    @pytest.mark.parametrize(
        ("options", "deselected", "tests_ran"),
        [
            (_Options(file_or_dir=["tests/api"]), False, 3),
            (_Options(ignore=["tests/cli"]), False, 3),
            (_Options(ignore_glob=["*_cli.py"]), False, 3),
            (_Options(), True, 3),
            (_Options(), False, 0),
        ],
        ids=["positional-path", "ignore", "ignore-glob", "deselection", "nothing-executed"],
    )
    def test_each_narrowing_skips_the_diff(self, options: _Options, deselected: bool, tests_ran: int) -> None:
        assert run_was_narrowed(options, deselected=deselected, tests_ran=tests_ran)


# The reverse direction of ADR 0033 (#121): a stale concurrent_rollup
# declaration — the rollup call removed, the retryable 409 still declared — is
# caught by the full-suite sessionfinish diff in _declaration_honesty.py. These
# tests pin its declared side: every operation whose effective declaration
# carries the code, keyed (method, route template) like the observation ledger.
# They are load-bearing for a second reason: each builds its declaration through
# error_responses() and reads it back through the audit, which makes them the
# round-trip pin on the ERROR_CODES_KEY seam — the guard that catches the
# declaration's *shape* drifting while writer and reader still agree on the
# shared key name. That is why they outlive any refactor of
# _operations_declaring.
class TestOperationsDeclaring:
    def test_route_level_declarer_is_enumerated_by_method_and_template(self) -> None:
        widget_app = FastAPI()
        router = APIRouter()

        @router.patch("/widgets/{widget_id}", responses=error_responses(ErrorCode.CONCURRENT_ROLLUP))
        async def patch_widget(widget_id: int) -> None: ...

        @router.get("/widgets/{widget_id}", responses=error_responses(ErrorCode.NOT_FOUND))
        async def get_widget(widget_id: int) -> None: ...

        widget_app.include_router(router, prefix="/api/v1")

        assert _operations_declaring(widget_app, ErrorCode.CONCURRENT_ROLLUP) == {("PATCH", "/widgets/{widget_id}")}

    def test_include_level_declarer_is_enumerated(self) -> None:
        # The declaration lives on the include, not route.responses (#120),
        # and must still count as declared or every include-declared operation
        # would read as stale.
        widget_app = _not_found_raising_app(error_responses(ErrorCode.CONCURRENT_ROLLUP))

        assert _operations_declaring(widget_app, ErrorCode.CONCURRENT_ROLLUP) == {("GET", "/widgets/{widget_id}")}

    def test_stale_message_names_only_unobserved_declarers(self) -> None:
        widget_app = _not_found_raising_app(error_responses(ErrorCode.CONCURRENT_ROLLUP))
        key = ("GET", "/widgets/{widget_id}")
        with observation_scope(key, synthetic=True):
            message = stale_rollup_declaration_message(widget_app)
            assert message is not None
            assert "GET /widgets/{widget_id}" in message

            record_observation(key)
            assert stale_rollup_declaration_message(widget_app) is None
