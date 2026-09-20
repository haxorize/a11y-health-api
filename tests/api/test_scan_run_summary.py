from httpx import AsyncClient
from pytest import approx
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import assert_error, make_scan_run_with_parents, make_score_snapshot


async def test_get_scan_run_summary(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    await make_score_snapshot(
        db_session,
        app_id=scan_run.app_id,
        scan_run_id=scan_run.id,
        score=0.8,
        total_violations=10,
        pages_with_violations=3,
        pages_with_critical_violations=1,
        total_pages=5,
    )

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/summary")
    assert response.status_code == 200

    data = response.json()
    assert data["total_violations"] == 10
    assert data["pages_with_violations"] == 3
    assert data["pages_with_critical_violations"] == 1
    assert data["total_pages"] == 5
    assert data["score"] == approx(0.8)
    assert "avg_violations_per_page" not in data
    assert "pct_pages_with_violations" not in data
    assert "pct_pages_with_critical_violations" not in data


async def test_get_scan_run_summary_pending_returns_404(
    db_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/summary")
    assert_error(response, 404, "not_found", message_contains=f"scan run summary {scan_run.id}")


async def test_get_scan_run_summary_not_found(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/scan-runs/999999/summary")
    # "scan run 999999", never "scan run summary 999999": the Scan Run's own
    # guard answers, not the summary lookup falling through.
    assert_error(response, 404, "not_found", message_contains="scan run 999999")
