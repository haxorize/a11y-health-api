from typing import Any

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.scan_run import ScanRunStatus
from tests.factories import make_app, make_org_unit, make_scan_run


async def test_create_page_result(
    db_client: AsyncClient, db_session: AsyncSession, axe_payload: dict[str, Any]
) -> None:
    org_unit = await make_org_unit(db_session)
    app = await make_app(db_session, org_unit_id=org_unit.id)
    scan_run = await make_scan_run(db_session, app_id=app.id)

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
    org_unit = await make_org_unit(db_session)
    app = await make_app(db_session, org_unit_id=org_unit.id)
    scan_run = await make_scan_run(db_session, app_id=app.id, status=ScanRunStatus.COMPLETED)

    response = await db_client.post(
        f"/api/v1/scan-runs/{scan_run.id}/pages",
        json=axe_payload,
    )
    assert response.status_code == 409


async def test_reject_malformed_json(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    app = await make_app(db_session, org_unit_id=org_unit.id)
    scan_run = await make_scan_run(db_session, app_id=app.id)

    response = await db_client.post(
        f"/api/v1/scan-runs/{scan_run.id}/pages",
        json={"not": "axe-json"},
    )
    assert response.status_code == 422


async def test_reject_missing_findings_key(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    app = await make_app(db_session, org_unit_id=org_unit.id)
    scan_run = await make_scan_run(db_session, app_id=app.id)

    response = await db_client.post(
        f"/api/v1/scan-runs/{scan_run.id}/pages",
        json={"testSubject": {"fileName": "https://example.com"}},
    )
    assert response.status_code == 422
