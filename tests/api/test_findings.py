from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.enums import FindingType, Impact
from tests.factories import (
    make_node_finding,
    make_page_result,
    make_rule_finding,
    make_scan_run_with_parents,
)


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
    assert finding["wcag_criteria"] == ["1.4.3"]
    assert finding["classifications"] == [{"standard": "wcag", "version": "2.0", "level": "AA"}]


async def test_list_findings_empty(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/findings")

    assert response.status_code == 200
    assert response.json() == []


async def test_list_findings_scan_run_not_found(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/scan-runs/999/findings")

    assert response.status_code == 404


async def test_filter_by_type(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    await make_rule_finding(
        db_session, page_result_id=page.id, finding_type=FindingType.VIOLATION, rule_id="color-contrast"
    )
    await make_rule_finding(
        db_session, page_result_id=page.id, finding_type=FindingType.INCOMPLETE, rule_id="image-alt"
    )

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/findings", params={"type": "violation"})

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["rule_id"] == "color-contrast"


async def test_filter_by_type_multi(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    await make_rule_finding(
        db_session, page_result_id=page.id, finding_type=FindingType.VIOLATION, rule_id="color-contrast"
    )
    await make_rule_finding(
        db_session, page_result_id=page.id, finding_type=FindingType.INCOMPLETE, rule_id="image-alt"
    )

    response = await db_client.get(
        f"/api/v1/scan-runs/{scan_run.id}/findings",
        params=[("type", "violation"), ("type", "incomplete")],
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2


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


async def test_filter_by_impact_multi(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    await make_rule_finding(db_session, page_result_id=page.id, impact=Impact.CRITICAL, rule_id="image-alt")
    await make_rule_finding(db_session, page_result_id=page.id, impact=Impact.MINOR, rule_id="meta-viewport")
    await make_rule_finding(db_session, page_result_id=page.id, impact=Impact.MODERATE, rule_id="tabindex")

    response = await db_client.get(
        f"/api/v1/scan-runs/{scan_run.id}/findings",
        params=[("impact", "critical"), ("impact", "minor")],
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    rule_ids = {f["rule_id"] for f in data}
    assert rule_ids == {"image-alt", "meta-viewport"}


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


async def test_filter_by_category_multi(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    await make_rule_finding(db_session, page_result_id=page.id, category="color", rule_id="color-contrast")
    await make_rule_finding(db_session, page_result_id=page.id, category="keyboard", rule_id="tabindex")
    await make_rule_finding(db_session, page_result_id=page.id, category="forms", rule_id="label")

    response = await db_client.get(
        f"/api/v1/scan-runs/{scan_run.id}/findings",
        params=[("category", "color"), ("category", "forms")],
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    rule_ids = {f["rule_id"] for f in data}
    assert rule_ids == {"color-contrast", "label"}


async def test_filter_by_wcag_criteria(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    await make_rule_finding(db_session, page_result_id=page.id, wcag_criteria=["1.4.3"], rule_id="color-contrast")
    await make_rule_finding(db_session, page_result_id=page.id, wcag_criteria=["2.4.4"], rule_id="link-name")

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/findings", params={"wcag_criterion": "2.4.4"})

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["rule_id"] == "link-name"


async def test_filter_by_wcag_criteria_multi(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    await make_rule_finding(db_session, page_result_id=page.id, wcag_criteria=["1.4.3"], rule_id="color-contrast")
    await make_rule_finding(db_session, page_result_id=page.id, wcag_criteria=["2.4.4"], rule_id="link-name")
    await make_rule_finding(db_session, page_result_id=page.id, wcag_criteria=["4.1.2"], rule_id="aria-roles")

    response = await db_client.get(
        f"/api/v1/scan-runs/{scan_run.id}/findings",
        params=[("wcag_criterion", "1.4.3"), ("wcag_criterion", "2.4.4")],
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    rule_ids = {f["rule_id"] for f in data}
    assert rule_ids == {"color-contrast", "link-name"}


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


async def test_filter_by_classification_multi_select(db_client: AsyncClient, db_session: AsyncSession) -> None:
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
    await make_rule_finding(
        db_session,
        page_result_id=page.id,
        rule_id="aria-roles",
        classifications=[{"standard": "wcag", "version": "2.1", "level": "AA"}],
    )

    response = await db_client.get(
        f"/api/v1/scan-runs/{scan_run.id}/findings",
        params=[("classification", "wcag2aa"), ("classification", "best-practice")],
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    rule_ids = {f["rule_id"] for f in data}
    assert rule_ids == {"color-contrast", "skip-link"}


async def test_filter_by_classification_multi(db_client: AsyncClient, db_session: AsyncSession) -> None:
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


async def test_filters_combine_with_and(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    await make_rule_finding(
        db_session, page_result_id=page.id, impact=Impact.CRITICAL, category="color", rule_id="color-contrast"
    )
    await make_rule_finding(
        db_session, page_result_id=page.id, impact=Impact.CRITICAL, category="keyboard", rule_id="tabindex"
    )
    await make_rule_finding(
        db_session, page_result_id=page.id, impact=Impact.MINOR, category="color", rule_id="meta-viewport"
    )

    response = await db_client.get(
        f"/api/v1/scan-runs/{scan_run.id}/findings",
        params={"impact": "critical", "category": "color"},
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["rule_id"] == "color-contrast"


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


async def test_get_finding_detail(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    finding = await make_rule_finding(db_session, page_result_id=page.id)
    node = await make_node_finding(
        db_session,
        rule_finding_id=finding.id,
        html="<span>bad</span>",
        target=[".main > span"],
        failure_summary="Insufficient contrast",
        checks={"any": [{"id": "color-contrast", "data": {}, "message": "low ratio"}], "all": [], "none": []},
    )

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/findings/{finding.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == finding.id
    assert data["rule_id"] == "color-contrast"
    assert len(data["node_findings"]) == 1
    nf = data["node_findings"][0]
    assert nf["id"] == node.id
    assert nf["html"] == "<span>bad</span>"
    assert nf["target"] == [".main > span"]
    assert nf["impact"] == "serious"
    assert nf["failure_summary"] == "Insufficient contrast"
    assert nf["checks"] == {
        "any": [{"id": "color-contrast", "data": {}, "message": "low ratio"}],
        "all": [],
        "none": [],
    }


async def test_get_finding_not_found(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/findings/999")

    assert response.status_code == 404


async def test_get_finding_wrong_scan_run(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run_1 = await make_scan_run_with_parents(db_session)
    scan_run_2 = await make_scan_run_with_parents(db_session, slug="other-app")
    page = await make_page_result(db_session, scan_run_id=scan_run_1.id)
    finding = await make_rule_finding(db_session, page_result_id=page.id)

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run_2.id}/findings/{finding.id}")

    assert response.status_code == 404
