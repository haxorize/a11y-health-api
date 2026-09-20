from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.enums import ScanRunStatus
from tests.factories import assert_error, make_scan_run_with_parents


async def test_create_page_result(
    db_client: AsyncClient, db_session: AsyncSession, axe_payload: dict[str, Any]
) -> None:
    scan_run = await make_scan_run_with_parents(db_session)

    response = await db_client.post(
        f"/api/v1/scan-runs/{scan_run.id}/pages",
        json=axe_payload,
    )
    assert response.status_code == 201
    data = response.json()
    assert data["scan_run_id"] == scan_run.id
    assert data["url"] == "https://www.humana.com/"
    assert data["passes_count"] == 44
    assert data["inapplicable_count"] == 46
    assert data["page_health"] is None
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


async def test_reject_upload_on_completed_scan_run(
    db_client: AsyncClient, db_session: AsyncSession, axe_payload: dict[str, Any]
) -> None:
    scan_run = await make_scan_run_with_parents(db_session, status=ScanRunStatus.COMPLETED)

    response = await db_client.post(
        f"/api/v1/scan-runs/{scan_run.id}/pages",
        json=axe_payload,
    )
    assert_error(response, 409, "scan_run_completed")


# One representative of the invalid-axe-payload 400 path; the validation rules
# themselves are tested at the schema seam (tests/schemas/test_axe_payload.py).
async def test_reject_invalid_axe_payload(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)

    response = await db_client.post(
        f"/api/v1/scan-runs/{scan_run.id}/pages",
        json={"not": "axe-json"},
    )
    assert_error(response, 400, "invalid_axe_payload")


# A present-but-malformed `name` or `endTime` is the declared 400, because the
# boundary types and validates the identity fields. Pinned over HTTP because
# the claim is about the wire, not the rule (the rule is at the schema seam).
@pytest.mark.parametrize(("field", "value"), [("name", 42), ("endTime", "last Tuesday")])
async def test_reject_malformed_identity_field(
    db_client: AsyncClient, db_session: AsyncSession, axe_payload: dict[str, Any], field: str, value: object
) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    axe_payload[field] = value

    response = await db_client.post(f"/api/v1/scan-runs/{scan_run.id}/pages", json=axe_payload)
    assert_error(response, 400, "invalid_axe_payload")


async def test_reject_upload_to_missing_scan_run(db_client: AsyncClient, axe_payload: dict[str, Any]) -> None:
    response = await db_client.post("/api/v1/scan-runs/999999/pages", json=axe_payload)
    assert_error(response, 404, "not_found")


async def test_invalid_payload_outranks_missing_scan_run(db_client: AsyncClient) -> None:
    # The service parses before the existence lookup, so the payload verdict is
    # the same whichever run it names. Pinned because the order is three
    # statements inside a service, not something visible at the route.
    response = await db_client.post("/api/v1/scan-runs/999999/pages", json={"not": "axe-json"})
    assert_error(response, 400, "invalid_axe_payload")
