import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.error_contract import ERROR_MODES, ErrorBody, ErrorCode, error_responses, response_for
from a11y_health.core.exceptions import (
    CircularReferenceError,
    ConcurrentRollupError,
    DomainError,
    DuplicateRootError,
    DuplicateSlugError,
    EmptyScanRunError,
    HasDependentsError,
    InvalidAxePayloadError,
    InvalidStatusTransitionError,
    NotFoundError,
    ScanRunCompletedError,
)
from a11y_health.core.pagination import InvalidCursorError
from a11y_health.main import app
from a11y_health.models.enums import ScanRunStatus
from a11y_health.services import scoring_orchestration
from tests._declaration_honesty import OBSERVED_ROLLUP_OPERATIONS, request_scope
from tests.factories import (
    make_app_with_org_unit,
    make_org_unit,
    make_page_result,
    make_scan_run_with_parents,
)

_MODE_EXAMPLES: list[DomainError] = [
    NotFoundError("App", 42),
    DuplicateRootError("Org unit", 1),
    DuplicateSlugError("my-app"),
    HasDependentsError("Org unit", 7),
    InvalidStatusTransitionError("Scan run", 3, ScanRunStatus.COMPLETED, ScanRunStatus.PENDING),
    ScanRunCompletedError(3),
    EmptyScanRunError(3),
    CircularReferenceError("Org unit", 1, 2),
    ConcurrentRollupError("Org unit", 1),
    InvalidCursorError(),
    InvalidAxePayloadError("findings: Field required"),
]


def _domain_error_types() -> set[type[DomainError]]:
    def walk(cls: type[DomainError]) -> set[type[DomainError]]:
        return set(cls.__subclasses__()).union(*(walk(sub) for sub in cls.__subclasses__()))

    return walk(DomainError)


def test_every_domain_error_mode_has_a_table_entry() -> None:
    assert set(ERROR_MODES) == _domain_error_types()


def test_exactly_one_code_per_mode_and_vocabulary_is_closed() -> None:
    codes = [mode.code for mode in ERROR_MODES.values()]
    assert len(codes) == len(set(codes))
    assert set(codes) == set(ErrorCode)


def test_mode_examples_cover_every_table_entry() -> None:
    assert {type(exc) for exc in _MODE_EXAMPLES} == set(ERROR_MODES)


def test_internal_validation_failure_is_not_disguised_as_a_client_error() -> None:
    # No app-level handler may catch pydantic's ValidationError: the framework's
    # own shape validation produces the only 422, and an internal validation
    # failure escaping the domain surfaces as a 500.
    assert ValidationError not in app.exception_handlers


def test_error_responses_groups_modes_by_status() -> None:
    declared = error_responses(ErrorCode.NOT_FOUND, ErrorCode.DUPLICATE_SLUG, ErrorCode.HAS_DEPENDENTS)
    assert set(declared) == {404, 409}
    assert declared[404]["model"] is ErrorBody
    assert declared[404]["x-error-codes"] == [ErrorCode.NOT_FOUND]
    assert declared[409]["x-error-codes"] == [ErrorCode.DUPLICATE_SLUG, ErrorCode.HAS_DEPENDENTS]
    assert "duplicate_slug" in declared[409]["description"]
    assert "has_dependents" in declared[409]["description"]


@pytest.mark.parametrize("exc", _MODE_EXAMPLES, ids=lambda e: type(e).__name__)
def test_response_carries_declared_status_and_code(exc: DomainError) -> None:
    response = response_for(exc)
    mode = ERROR_MODES[type(exc)]
    assert response.status_code == mode.status
    body = ErrorBody.model_validate_json(bytes(response.body))
    assert body.code == mode.code
    assert body.message == str(exc)


# Rollup-race 409s never fire organically in endpoint tests, so the honesty
# shim can't catch a missing concurrent_rollup declaration at the response;
# the instrumentation in tests/_declaration_honesty.py asserts it at the raise
# site instead, on every rollup any test provokes over HTTP (#113). Passthrough
# outside a request context is proven organically by the service-layer suite,
# which calls the wrapped rollup functions directly.
async def test_rollup_from_operation_without_declared_concurrent_rollup_fails() -> None:
    route = SimpleNamespace(path="/widgets/{widget_id}", responses=error_responses(ErrorCode.NOT_FOUND))
    scope = {"method": "PATCH", "path": "/api/v1/widgets/1", "route": route}
    with request_scope(scope), pytest.raises(AssertionError, match="concurrent_rollup"):
        # session=None proves the check fires before any rollup work runs.
        await scoring_orchestration.on_app_deleted(None, 1, 2)  # ty: ignore[invalid-argument-type]


def test_no_src_caller_binds_a_rollup_raiser_by_from_import() -> None:
    # The instrumentation patches score_snapshot module attributes, so it only
    # intercepts attribute-access call sites; a `from ...score_snapshot import
    # rollup_*` binding taken at import time would bypass enforcement entirely
    # (ADR 0033). This pins the calling convention the mechanism depends on.
    src_root = Path(scoring_orchestration.__file__).parent.parent
    pattern = re.compile(r"from\s+[\w.]*score_snapshot\s+import\s+(\([^)]*\)|[^\n]+)")
    offenders = [
        str(path.relative_to(src_root))
        for path in src_root.rglob("*.py")
        if any("rollup_" in match for match in pattern.findall(path.read_text()))
    ]
    assert not offenders, f"rollup raisers must be called as score_snapshot attributes, not from-imported: {offenders}"


# Enforcement depth is the suite's coverage of rollup-triggering variants, so
# each known rollup-triggering operation gets an explicit canary driving its
# triggering variant over HTTP — discarding the key first proves this test's
# own request was observed, not an earlier test's. A canary fails if the
# variant stops triggering rollups (coverage lost) or, via the raise-site
# assert, if the operation drops its concurrent_rollup declaration.
class TestRollupObservationCanaries:
    # Keys use the matched route's own template — the app's include mode
    # doesn't expose the /api/v1 mount prefix to the route object at handler
    # time.
    async def test_app_delete(self, db_client: AsyncClient, db_session: AsyncSession) -> None:
        app_row = await make_app_with_org_unit(db_session, slug="canary-app-delete")
        key = ("DELETE", "/apps/{app_id}")
        OBSERVED_ROLLUP_OPERATIONS.discard(key)

        response = await db_client.delete(f"/api/v1/apps/{app_row.id}")
        assert response.status_code == 204
        assert key in OBSERVED_ROLLUP_OPERATIONS

    async def test_app_reassignment(self, db_client: AsyncClient, db_session: AsyncSession) -> None:
        app_row = await make_app_with_org_unit(db_session, slug="canary-app-reassign")
        target = await make_org_unit(db_session, name="Canary Target", parent_id=app_row.org_unit_id)
        key = ("PATCH", "/apps/{app_id}")
        OBSERVED_ROLLUP_OPERATIONS.discard(key)

        response = await db_client.patch(f"/api/v1/apps/{app_row.id}", json={"org_unit_id": target.id})
        assert response.status_code == 200
        assert key in OBSERVED_ROLLUP_OPERATIONS

    async def test_org_unit_reparenting(self, db_client: AsyncClient, db_session: AsyncSession) -> None:
        root = await make_org_unit(db_session, name="Canary Root")
        new_parent = await make_org_unit(db_session, name="Canary Parent", parent_id=root.id)
        child = await make_org_unit(db_session, name="Canary Child", parent_id=root.id)
        key = ("PATCH", "/org-units/{org_unit_id}")
        OBSERVED_ROLLUP_OPERATIONS.discard(key)

        response = await db_client.patch(f"/api/v1/org-units/{child.id}", json={"parent_id": new_parent.id})
        assert response.status_code == 200
        assert key in OBSERVED_ROLLUP_OPERATIONS

    async def test_scan_run_completion(self, db_client: AsyncClient, db_session: AsyncSession) -> None:
        scan_run = await make_scan_run_with_parents(db_session, slug="canary-run-complete")
        await make_page_result(db_session, scan_run_id=scan_run.id)
        key = ("PATCH", "/scan-runs/{scan_run_id}")
        OBSERVED_ROLLUP_OPERATIONS.discard(key)

        response = await db_client.patch(f"/api/v1/scan-runs/{scan_run.id}", json={"status": "completed"})
        assert response.status_code == 200
        assert key in OBSERVED_ROLLUP_OPERATIONS

    async def test_scan_run_delete(self, db_client: AsyncClient, db_session: AsyncSession) -> None:
        scan_run = await make_scan_run_with_parents(db_session, slug="canary-run-delete")
        key = ("DELETE", "/scan-runs/{scan_run_id}")
        OBSERVED_ROLLUP_OPERATIONS.discard(key)

        response = await db_client.delete(f"/api/v1/scan-runs/{scan_run.id}")
        assert response.status_code == 204
        assert key in OBSERVED_ROLLUP_OPERATIONS


async def test_missing_app_produces_declared_coded_not_found(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/apps/999999")
    assert response.status_code == 404
    assert response.json() == {"code": "not_found", "message": "App 999999 not found"}

    # The same mode must be declared on the operation, referencing the shared body schema.
    spec = app.openapi()
    declared = spec["paths"]["/api/v1/apps/{app_id}"]["get"]["responses"]
    assert "404" in declared
    schema_ref = declared["404"]["content"]["application/json"]["schema"]["$ref"]
    assert schema_ref == "#/components/schemas/ErrorBody"
