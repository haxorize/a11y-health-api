from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from a11y_health.models.classification import Classification
from a11y_health.models.enums import Category, FindingType, Impact
from a11y_health.models.node_finding import NodeFinding
from a11y_health.models.page_result import PageResult
from a11y_health.models.rule_finding import RuleFinding
from a11y_health.services.page_result import create_page_result
from tests.factories import (
    make_axe_payload,
    make_scan_run_with_parents,
    make_violation,
)


@pytest.fixture
async def page_result(db_session: AsyncSession, axe_payload: dict[str, Any]) -> PageResult:
    scan_run = await make_scan_run_with_parents(db_session)
    return await create_page_result(db_session, scan_run.id, axe_payload)


async def test_violations_stored_as_rule_findings(db_session: AsyncSession, page_result: PageResult) -> None:
    stmt = select(RuleFinding).where(
        RuleFinding.page_result_id == page_result.id,
        RuleFinding.type == FindingType.VIOLATION,
    )
    result = await db_session.execute(stmt)
    violations = result.scalars().all()

    assert len(violations) == 1
    v = violations[0]
    assert v.rule_id == "svg-img-alt"
    assert v.impact == Impact.SERIOUS
    assert (
        v.description
        == "Ensure <svg> elements with an img, graphics-document or graphics-symbol role have an accessible text"
    )
    assert v.help == "<svg> elements with an img role must have an alternative text"
    assert v.help_url == "https://dequeuniversity.com/rules/axe/4.10/svg-img-alt?application=playwright"


async def test_node_findings_stored(db_session: AsyncSession, axe_payload: dict[str, Any]) -> None:
    # Red when the mint transposes any two check buckets. Every stored node in
    # the fixture carries empty `all` and `none`, so the node under test gets a
    # distinct check in each, or an all/none swap would pass unseen.
    source = axe_payload["findings"]["violations"][0]["nodes"][0]
    source["all"] = [{**source["any"][0], "id": "pinned-all-check"}]
    source["none"] = [{**source["any"][0], "id": "pinned-none-check"}]
    scan_run = await make_scan_run_with_parents(db_session)
    page_result = await create_page_result(db_session, scan_run.id, axe_payload)

    stmt = select(RuleFinding).where(
        RuleFinding.page_result_id == page_result.id,
        RuleFinding.rule_id == "svg-img-alt",
    )
    result = await db_session.execute(stmt)
    violation = result.scalars().one()

    stmt = (
        select(NodeFinding)
        .options(undefer(NodeFinding.checks))
        .where(NodeFinding.rule_finding_id == violation.id)
        .order_by(NodeFinding.id)
    )
    result = await db_session.execute(stmt)
    nodes = result.scalars().all()

    assert len(nodes) == 3
    node = nodes[0]
    assert "<svg" in node.html
    assert node.target == source["target"]
    assert node.impact == Impact.SERIOUS
    assert node.failure_summary == source["failureSummary"]

    def check_ids(checks: dict[str, Any]) -> dict[str, list[str]]:
        return {bucket: [check["id"] for check in checks[bucket]] for bucket in ("any", "all", "none")}

    assert check_ids(node.checks) == check_ids(source)


async def test_classifications_extracted(db_session: AsyncSession, page_result: PageResult) -> None:
    stmt = select(RuleFinding).where(
        RuleFinding.page_result_id == page_result.id,
        RuleFinding.rule_id == "svg-img-alt",
    )
    result = await db_session.execute(stmt)
    finding = result.scalars().first()
    assert finding is not None

    assert Classification(standard="wcag", version="2.0", level="A") in finding.classifications

    stmt = select(RuleFinding).where(
        RuleFinding.page_result_id == page_result.id,
        RuleFinding.rule_id == "color-contrast",
    )
    result = await db_session.execute(stmt)
    finding = result.scalars().first()
    assert finding is not None

    assert Classification(standard="wcag", version="2.0", level="AA") in finding.classifications


async def test_best_practice_classification_stored_without_null_members(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    payload = make_axe_payload(violations=[make_violation("region", "moderate")])
    await create_page_result(db_session, scan_run.id, payload)

    stmt = select(text("classifications")).select_from(RuleFinding).where(RuleFinding.rule_id == "region")
    stored = (await db_session.execute(stmt)).scalar_one()

    # Compact JSONB, matching the GIN containment targets the classification
    # filter builds.
    assert stored == [{"standard": "best-practice"}]


async def test_wcag21_classification_stored_from_ingested_tags(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    payload = make_axe_payload(violations=[make_violation("target-size", "serious", tags=["wcag21aa", "cat.color"])])
    await create_page_result(db_session, scan_run.id, payload)

    stmt = select(text("classifications")).select_from(RuleFinding).where(RuleFinding.rule_id == "target-size")
    stored = (await db_session.execute(stmt)).scalar_one()

    # Deliberately literal — the ingest-path pin for a 2.1 stored shape,
    # independent of the token map.
    assert stored == [{"standard": "wcag", "version": "2.1", "level": "AA"}]


async def test_category_and_wcag_criterion_extracted(db_session: AsyncSession, page_result: PageResult) -> None:
    stmt = select(RuleFinding).where(
        RuleFinding.page_result_id == page_result.id,
        RuleFinding.rule_id == "svg-img-alt",
    )
    result = await db_session.execute(stmt)
    finding = result.scalars().first()
    assert finding is not None

    assert finding.category == Category.TEXT_ALTERNATIVES
    assert finding.wcag_criteria == ["1.1.1"]

    stmt = select(RuleFinding).where(
        RuleFinding.page_result_id == page_result.id,
        RuleFinding.rule_id == "color-contrast",
    )
    result = await db_session.execute(stmt)
    finding = result.scalars().first()
    assert finding is not None

    assert finding.category == Category.COLOR
    assert finding.wcag_criteria == ["1.4.3"]


async def test_incompletes_stored_as_incomplete_type(db_session: AsyncSession, page_result: PageResult) -> None:
    stmt = select(RuleFinding).where(
        RuleFinding.page_result_id == page_result.id,
        RuleFinding.type == FindingType.INCOMPLETE,
    )
    result = await db_session.execute(stmt)
    incompletes = result.scalars().all()

    assert len(incompletes) == 2
    rule_ids = {r.rule_id for r in incompletes}
    assert rule_ids == {"aria-prohibited-attr", "color-contrast"}
