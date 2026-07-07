import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from a11y_health.core.error_contract import ERROR_MODES, ErrorBody, ErrorCode, error_responses, response_for
from a11y_health.core.exceptions import (
    CircularReferenceError,
    DomainError,
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

_MODE_EXAMPLES: list[DomainError] = [
    NotFoundError("App", 42),
    DuplicateSlugError("my-app"),
    HasDependentsError("Org unit", 7),
    InvalidStatusTransitionError("Scan run", 3, ScanRunStatus.COMPLETED, ScanRunStatus.PENDING),
    ScanRunCompletedError(3),
    EmptyScanRunError(3),
    CircularReferenceError("Org unit", 1, 2),
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
