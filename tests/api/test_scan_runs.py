from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.scan_run import ScanRunStatus
from tests.factories import make_app, make_org_unit, make_scan_run


async def test_create_scan_run(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    app = await make_app(db_session, org_unit_id=org_unit.id)

    response = await db_client.post(
        f"/api/v1/apps/{app.id}/scan-runs",
        json={"scanned_at": "2026-04-01T12:00:00Z"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["app_id"] == app.id
    assert data["status"] == "pending"
    assert data["scanned_at"] == "2026-04-01T12:00:00Z"
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


async def test_create_scan_run_invalid_app(db_client: AsyncClient) -> None:
    response = await db_client.post(
        "/api/v1/apps/999999/scan-runs",
        json={"scanned_at": "2026-04-01T12:00:00Z"},
    )
    assert response.status_code == 404


async def test_list_scan_runs(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    app = await make_app(db_session, org_unit_id=org_unit.id)
    await make_scan_run(db_session, app_id=app.id)
    await make_scan_run(db_session, app_id=app.id)

    response = await db_client.get(f"/api/v1/apps/{app.id}/scan-runs")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert all(r["app_id"] == app.id for r in data)


async def test_get_scan_run(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    app = await make_app(db_session, org_unit_id=org_unit.id)
    scan_run = await make_scan_run(db_session, app_id=app.id)

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == scan_run.id
    assert data["app_id"] == app.id


async def test_get_scan_run_not_found(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/scan-runs/999999")
    assert response.status_code == 404


async def test_update_scan_run_status(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    app = await make_app(db_session, org_unit_id=org_unit.id)
    scan_run = await make_scan_run(db_session, app_id=app.id)

    response = await db_client.patch(
        f"/api/v1/scan-runs/{scan_run.id}",
        json={"status": "completed"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "completed"


async def test_update_scan_run_invalid_transition(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    app = await make_app(db_session, org_unit_id=org_unit.id)
    scan_run = await make_scan_run(db_session, app_id=app.id, status=ScanRunStatus.COMPLETED)

    response = await db_client.patch(
        f"/api/v1/scan-runs/{scan_run.id}",
        json={"status": "pending"},
    )
    assert response.status_code == 409
