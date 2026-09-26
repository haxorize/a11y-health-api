import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from a11y_health.core.error_contract import (
    ERROR_CODES_KEY,
    ERROR_MODES,
    ErrorBody,
    ErrorCode,
    error_responses,
    response_for,
)
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
from a11y_health.models.app import App
from a11y_health.models.enums import ScanRunStatus
from a11y_health.models.org_unit import OrgUnit
from a11y_health.models.scan_run import ScanRun
from a11y_health.models.score_snapshot import ScoreSnapshot

_MODE_EXAMPLES: list[DomainError] = [
    NotFoundError(App, 42),
    DuplicateRootError(OrgUnit, 1),
    DuplicateSlugError("my-app"),
    HasDependentsError(OrgUnit, 7),
    InvalidStatusTransitionError(ScanRun, 3, ScanRunStatus.COMPLETED, ScanRunStatus.PENDING),
    ScanRunCompletedError(3),
    EmptyScanRunError(3),
    CircularReferenceError(OrgUnit, 1, 2),
    ConcurrentRollupError(OrgUnit, 1),
    InvalidCursorError(),
    InvalidAxePayloadError("findings: Field required"),
]


# Each mode naming an entity resolves its label from the one table. Breaks
# when a mode derives the label any other way, `OrgUnit.__name__` included.
@pytest.mark.parametrize(
    ("exc", "message"),
    [
        pytest.param(NotFoundError(ScoreSnapshot, 5), "Scan run summary 5 not found", id="not_found"),
        pytest.param(
            DuplicateRootError(OrgUnit),
            "A top-level org unit already exists: only one is allowed",
            id="duplicate_root_race",
        ),
        pytest.param(
            DuplicateRootError(OrgUnit, 1),
            "Org unit 1 is already the top-level org unit: only one is allowed",
            id="duplicate_root",
        ),
        pytest.param(
            CircularReferenceError(OrgUnit, 1, 2),
            "Org unit 1 cannot have 2 as parent: circular reference",
            id="circular_reference",
        ),
        pytest.param(
            InvalidStatusTransitionError(ScanRun, 3, ScanRunStatus.COMPLETED, ScanRunStatus.PENDING),
            "Scan run 3 cannot transition from completed to pending",
            id="invalid_status_transition",
        ),
        pytest.param(
            ConcurrentRollupError(OrgUnit, 1),
            "Org unit 1 score was updated by another request at the same time; retry the request",
            id="concurrent_rollup",
        ),
        pytest.param(
            HasDependentsError(OrgUnit, 7),
            "Cannot delete Org unit 7: it has dependent records",
            id="has_dependents",
        ),
    ],
)
def test_mode_names_its_entity_by_the_table_label(exc: DomainError, message: str) -> None:
    assert str(exc) == message


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


def test_declared_code_key_is_the_published_vendor_extension() -> None:
    # The only assertion left holding the literal. Every other reader now goes
    # through the constant, which makes writer and reader the same symbol — so
    # without this, renaming its *value* would rewrite all 44 keys in the
    # published document with the whole suite still green.
    assert ERROR_CODES_KEY == "x-error-codes"


def test_error_responses_groups_modes_by_status() -> None:
    declared = error_responses(ErrorCode.NOT_FOUND, ErrorCode.DUPLICATE_SLUG, ErrorCode.HAS_DEPENDENTS)
    assert set(declared) == {404, 409}
    assert declared[404]["model"] is ErrorBody
    assert declared[404][ERROR_CODES_KEY] == [ErrorCode.NOT_FOUND]
    assert declared[409][ERROR_CODES_KEY] == [ErrorCode.DUPLICATE_SLUG, ErrorCode.HAS_DEPENDENTS]
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


async def test_missing_app_produces_declared_coded_not_found(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/apps/999999")
    assert response.status_code == 404
    assert response.json() == {"code": "not_found", "message": "App 999999 not found"}

    # The same mode must be declared on the operation, referencing the shared
    # body schema.
    spec = app.openapi()
    declared = spec["paths"]["/api/v1/apps/{app_id}"]["get"]["responses"]
    assert "404" in declared
    schema_ref = declared["404"]["content"]["application/json"]["schema"]["$ref"]
    assert schema_ref == "#/components/schemas/ErrorBody"
