from httpx import AsyncClient
from pytest import approx
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_scan_run_with_parents, make_score_snapshot


async def test_get_scan_run_summary(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    await make_score_snapshot(
        db_session,
        app_id=scan_run.app_id,
        scan_run_id=scan_run.id,
        score=0.8,
        total_issues=10,
        pages_with_issues=3,
        pages_with_critical_issues=1,
        total_pages=5,
    )

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/summary")
    assert response.status_code == 200

    data = response.json()
    assert data["total_issues"] == 10
    assert data["pages_with_issues"] == 3
    assert data["pages_with_critical_issues"] == 1
    assert data["total_pages"] == 5
    assert data["avg_issues_per_page"] == approx(2.0)
    assert data["pct_pages_with_issues"] == approx(0.6)
    assert data["pct_pages_with_critical_issues"] == approx(0.2)
    assert data["score"] == approx(0.8)


async def test_get_scan_run_summary_pending_returns_404(
    db_client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/summary")
    assert response.status_code == 404


async def test_get_scan_run_summary_not_found(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/scan-runs/999999/summary")
    assert response.status_code == 404
