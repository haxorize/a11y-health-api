from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.enums import ScanRunStatus
from tests.factories import make_axe_payload, make_scan_run_with_parents


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
    assert response.status_code == 409


async def test_reject_malformed_json(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)

    response = await db_client.post(
        f"/api/v1/scan-runs/{scan_run.id}/pages",
        json={"not": "axe-json"},
    )
    assert response.status_code == 422


async def test_reject_missing_findings_key(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)

    response = await db_client.post(
        f"/api/v1/scan-runs/{scan_run.id}/pages",
        json={"testSubject": {"fileName": "https://example.com"}},
    )
    assert response.status_code == 422


async def test_reject_missing_url(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    payload = make_axe_payload()
    del payload["testSubject"]

    response = await db_client.post(f"/api/v1/scan-runs/{scan_run.id}/pages", json=payload)
    assert response.status_code == 422
    assert "url" in response.json()["detail"].lower()


async def test_reject_empty_url(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)

    response = await db_client.post(
        f"/api/v1/scan-runs/{scan_run.id}/pages",
        json=make_axe_payload(url=""),
    )
    assert response.status_code == 422
    assert "url" in response.json()["detail"].lower()


@pytest.mark.parametrize(
    ("section", "bad_value"),
    [("violations", "not-a-list"), ("incomplete", 42)],
)
async def test_reject_non_list_finding_section(
    db_client: AsyncClient, db_session: AsyncSession, section: str, bad_value: object
) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    payload = make_axe_payload()
    payload["findings"][section] = bad_value

    response = await db_client.post(f"/api/v1/scan-runs/{scan_run.id}/pages", json=payload)
    assert response.status_code == 422
    assert section in response.json()["detail"].lower()


async def test_reject_rule_missing_required_fields(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)

    response = await db_client.post(
        f"/api/v1/scan-runs/{scan_run.id}/pages",
        json=make_axe_payload(violations=[{"id": "some-rule"}]),
    )
    assert response.status_code == 422
    detail = response.json()["detail"].lower()
    assert "impact" in detail or "description" in detail or "help" in detail


async def test_reject_rule_missing_id(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)

    response = await db_client.post(
        f"/api/v1/scan-runs/{scan_run.id}/pages",
        json=make_axe_payload(violations=[{"impact": "serious", "description": "d", "help": "h", "helpUrl": "u"}]),
    )
    assert response.status_code == 422
    assert "id" in response.json()["detail"].lower()
