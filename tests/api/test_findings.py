from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.rule_finding import Impact
from tests.factories import make_page_result, make_rule_finding, make_scan_run_with_parents


async def test_list_findings(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page_result = await make_page_result(db_session, scan_run_id=scan_run.id)
    await make_rule_finding(db_session, page_result_id=page_result.id)

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/findings")

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    finding = data[0]
    assert finding["rule_id"] == "color-contrast"
    assert finding["impact"] == "serious"
    assert finding["category"] == "color"
    assert finding["wcag_criterion"] == "1.4.3"
    assert finding["classifications"] == [{"standard": "wcag", "version": "2.0", "level": "AA"}]


async def test_list_findings_empty(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/findings")

    assert response.status_code == 200
    assert response.json() == []


async def test_list_findings_scan_run_not_found(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/scan-runs/999/findings")

    assert response.status_code == 404


async def test_filter_by_impact(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    await make_rule_finding(db_session, page_result_id=page.id, impact=Impact.CRITICAL, rule_id="image-alt")
    await make_rule_finding(db_session, page_result_id=page.id, impact=Impact.MINOR, rule_id="meta-viewport")

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/findings", params={"impact": "critical"})

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["rule_id"] == "image-alt"


async def test_filter_by_category(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    await make_rule_finding(db_session, page_result_id=page.id, category="color", rule_id="color-contrast")
    await make_rule_finding(db_session, page_result_id=page.id, category="keyboard", rule_id="tabindex")

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/findings", params={"category": "keyboard"})

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["rule_id"] == "tabindex"


async def test_filter_by_wcag_criterion(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    await make_rule_finding(db_session, page_result_id=page.id, wcag_criterion="1.4.3", rule_id="color-contrast")
    await make_rule_finding(db_session, page_result_id=page.id, wcag_criterion="2.4.4", rule_id="link-name")

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/findings", params={"wcag_criterion": "2.4.4"})

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["rule_id"] == "link-name"


async def test_filter_by_classification(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    await make_rule_finding(
        db_session,
        page_result_id=page.id,
        rule_id="color-contrast",
        classifications=[{"standard": "wcag", "version": "2.0", "level": "AA"}],
    )
    await make_rule_finding(
        db_session,
        page_result_id=page.id,
        rule_id="skip-link",
        classifications=[{"standard": "best-practice"}],
    )

    response = await db_client.get(
        f"/api/v1/scan-runs/{scan_run.id}/findings", params={"classification": "best-practice"}
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["rule_id"] == "skip-link"


async def test_filter_by_classification_multi(db_client: AsyncClient, db_session: AsyncSession) -> None:
    """A rule with multiple classifications appears when filtering by any of them."""
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    await make_rule_finding(
        db_session,
        page_result_id=page.id,
        rule_id="color-contrast",
        classifications=[
            {"standard": "wcag", "version": "2.0", "level": "AA"},
            {"standard": "wcag", "version": "2.1", "level": "AA"},
        ],
    )

    r1 = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/findings", params={"classification": "wcag2aa"})
    r2 = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/findings", params={"classification": "wcag21aa"})

    d1, d2 = r1.json(), r2.json()
    assert len(d1) == 1
    assert len(d2) == 1
    assert d1[0]["rule_id"] == "color-contrast"
    assert d2[0]["rule_id"] == "color-contrast"


async def test_pagination(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    for i in range(3):
        await make_rule_finding(db_session, page_result_id=page.id, rule_id=f"rule-{i}")

    r1 = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/findings", params={"limit": 2})
    r2 = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/findings", params={"offset": 2, "limit": 2})

    assert len(r1.json()) == 2
    assert len(r2.json()) == 1
    assert r1.json()[0]["rule_id"] == "rule-0"
    assert r2.json()[0]["rule_id"] == "rule-2"
