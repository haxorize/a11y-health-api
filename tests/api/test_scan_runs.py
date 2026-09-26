import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import ConcurrentRollupError
from a11y_health.models.enums import ScanRunStatus
from a11y_health.models.org_unit import OrgUnit
from a11y_health.services import owner as owner_service
from tests.factories import (
    assert_error,
    make_app_with_org_unit,
    make_page_result,
    make_scan_run,
    make_scan_run_with_parents,
)


async def test_create_scan_run(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)

    response = await db_client.post(
        f"/api/v1/apps/{scan_run.app_id}/scan-runs",
        json={"scanned_at": "2026-04-01T12:00:00Z"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["app_id"] == scan_run.app_id
    assert data["status"] == ScanRunStatus.PENDING.value
    assert data["scanned_at"] == "2026-04-01T12:00:00Z"
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


@pytest.mark.parametrize("scanned_at", ["2026-04-01T12:00:00", "2026-04-01T17:00:00+05:00"])
async def test_create_scan_run_body_matches_get(
    db_client: AsyncClient, db_session: AsyncSession, scanned_at: str
) -> None:
    app = await make_app_with_org_unit(db_session)

    created = await db_client.post(f"/api/v1/apps/{app.id}/scan-runs", json={"scanned_at": scanned_at})
    # db_client shares one session across requests; expiring it makes the GET
    # read the row, as production's per-request session would.
    db_session.expire_all()
    fetched = await db_client.get(f"/api/v1/scan-runs/{created.json()['id']}")

    assert created.json() == fetched.json()


async def test_create_scan_run_invalid_app(db_client: AsyncClient) -> None:
    response = await db_client.post(
        "/api/v1/apps/999999/scan-runs",
        json={"scanned_at": "2026-04-01T12:00:00Z"},
    )
    assert response.status_code == 404


async def test_list_scan_runs(db_client: AsyncClient, db_session: AsyncSession) -> None:
    sr1 = await make_scan_run_with_parents(db_session)
    await make_scan_run(db_session, app_id=sr1.app_id)

    response = await db_client.get(f"/api/v1/apps/{sr1.app_id}/scan-runs")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert all(r["app_id"] == sr1.app_id for r in data["items"])


# Like the findings pin, this asserts that `total` crosses the wire; the count
# semantics are owned by the paginate suite. total ≠ len(items), so an
# accidental echo of the loaded rows can't pass.
async def test_list_scan_runs_total_counts_beyond_the_page(db_client: AsyncClient, db_session: AsyncSession) -> None:
    sr1 = await make_scan_run_with_parents(db_session)
    for _ in range(2):
        await make_scan_run(db_session, app_id=sr1.app_id)

    response = await db_client.get(f"/api/v1/apps/{sr1.app_id}/scan-runs", params={"limit": 1})
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["total"] == 3


async def test_list_scan_runs_invalid_app(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/apps/999999/scan-runs")
    assert response.status_code == 404


async def test_get_scan_run(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == scan_run.id
    assert data["app_id"] == scan_run.app_id


async def test_get_scan_run_not_found(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/scan-runs/999999")
    assert response.status_code == 404


async def test_update_scan_run_status(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    await make_page_result(db_session, scan_run_id=scan_run.id)

    response = await db_client.patch(
        f"/api/v1/scan-runs/{scan_run.id}",
        json={"status": ScanRunStatus.COMPLETED.value},
    )
    assert response.status_code == 200
    assert response.json()["status"] == ScanRunStatus.COMPLETED.value


async def test_complete_empty_scan_run_conflict(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)

    response = await db_client.patch(
        f"/api/v1/scan-runs/{scan_run.id}",
        json={"status": ScanRunStatus.COMPLETED.value},
    )
    assert_error(response, 409, "empty_scan_run", message_contains="no page results")


async def test_delete_scan_run(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)

    response = await db_client.delete(f"/api/v1/scan-runs/{scan_run.id}")
    assert response.status_code == 204

    get_response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}")
    assert get_response.status_code == 404


async def test_delete_scan_run_not_found(db_client: AsyncClient) -> None:
    response = await db_client.delete("/api/v1/scan-runs/999999")
    assert response.status_code == 404


async def test_delete_scan_run_losing_a_concurrent_rollup_returns_retryable_409(
    db_client: AsyncClient, db_session: AsyncSession, mocker
) -> None:
    app = await make_app_with_org_unit(db_session)
    scan_run = await make_scan_run(db_session, app_id=app.id)

    mocker.patch.object(
        owner_service,
        "_acquire_rollup_lock",
        side_effect=ConcurrentRollupError(OrgUnit, app.org_unit_id),
    )

    response = await db_client.delete(f"/api/v1/scan-runs/{scan_run.id}")
    assert_error(response, 409, "concurrent_rollup", message_contains="retry")


async def test_update_scan_run_invalid_transition(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session, status=ScanRunStatus.COMPLETED)

    response = await db_client.patch(
        f"/api/v1/scan-runs/{scan_run.id}",
        json={"status": ScanRunStatus.PENDING.value},
    )
    assert_error(
        response, 409, "invalid_status_transition", message_contains="cannot transition from completed to pending"
    )
