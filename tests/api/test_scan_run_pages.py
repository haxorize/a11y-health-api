from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.page_result import PageHealth
from a11y_health.models.rule_finding import FindingType, Impact
from tests.factories import make_page_result, make_rule_finding, make_scan_run_with_parents


async def test_get_scan_run_pages(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)

    page1 = await make_page_result(db_session, scan_run_id=scan_run.id, url="https://example.com/home")
    page1.page_health = PageHealth.CRITICAL
    await make_rule_finding(db_session, page_result_id=page1.id, impact=Impact.CRITICAL)
    await make_rule_finding(db_session, page_result_id=page1.id, impact=Impact.SERIOUS)
    # Incomplete should not count toward issues
    await make_rule_finding(
        db_session,
        page_result_id=page1.id,
        impact=Impact.MINOR,
        finding_type=FindingType.INCOMPLETE,
        rule_id="incomplete-rule",
    )

    page2 = await make_page_result(db_session, scan_run_id=scan_run.id, url="https://example.com/about")
    page2.page_health = PageHealth.GOOD

    await db_session.flush()

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/pages")
    assert response.status_code == 200

    data = response.json()
    assert len(data) == 2

    p1 = next(p for p in data if p["url"] == "https://example.com/home")
    assert p1["issues_count"] == 2
    assert p1["critical_issues_count"] == 1
    assert p1["page_health"] == "critical"

    p2 = next(p for p in data if p["url"] == "https://example.com/about")
    assert p2["issues_count"] == 0
    assert p2["critical_issues_count"] == 0
    assert p2["page_health"] == "good"


async def test_get_scan_run_pages_not_found(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/scan-runs/999999/pages")
    assert response.status_code == 404


async def test_get_scan_run_pages_empty(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/pages")
    assert response.status_code == 200
    assert response.json() == []


async def test_get_scan_run_pages_pagination(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    for i in range(3):
        await make_page_result(db_session, scan_run_id=scan_run.id, url=f"https://example.com/page{i}")

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/pages?offset=1&limit=1")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["url"] == "https://example.com/page1"
