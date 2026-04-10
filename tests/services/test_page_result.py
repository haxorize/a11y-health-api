from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import InvalidAxePayloadError
from a11y_health.models.node_finding import NodeFinding
from a11y_health.models.page_result import PageResult
from a11y_health.models.rule_finding import FindingType, Impact, RuleFinding
from a11y_health.services.page_result import create_page_result
from tests.factories import make_axe_payload, make_scan_run_with_parents


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


async def test_node_findings_stored(db_session: AsyncSession, page_result: PageResult) -> None:
    stmt = select(RuleFinding).where(
        RuleFinding.page_result_id == page_result.id,
        RuleFinding.type == FindingType.VIOLATION,
    )
    result = await db_session.execute(stmt)
    violation = result.scalars().first()
    assert violation is not None

    stmt = select(NodeFinding).where(NodeFinding.rule_finding_id == violation.id)
    result = await db_session.execute(stmt)
    nodes = result.scalars().all()

    assert len(nodes) == 3
    node = nodes[0]
    assert "<svg" in node.html
    assert isinstance(node.target, list)
    assert node.impact == Impact.SERIOUS
    assert node.failure_summary is not None
    assert "any" in node.checks
    assert "all" in node.checks
    assert "none" in node.checks


async def test_classifications_extracted(db_session: AsyncSession, page_result: PageResult) -> None:
    # svg-img-alt has tags: wcag2a, wcag111 → classification wcag 2.0 A
    stmt = select(RuleFinding).where(
        RuleFinding.page_result_id == page_result.id,
        RuleFinding.rule_id == "svg-img-alt",
    )
    result = await db_session.execute(stmt)
    finding = result.scalars().first()
    assert finding is not None

    assert {"standard": "wcag", "version": "2.0", "level": "A"} in finding.classifications

    # color-contrast (incomplete) has wcag2aa → wcag 2.0 AA
    stmt = select(RuleFinding).where(
        RuleFinding.page_result_id == page_result.id,
        RuleFinding.rule_id == "color-contrast",
    )
    result = await db_session.execute(stmt)
    finding = result.scalars().first()
    assert finding is not None

    assert {"standard": "wcag", "version": "2.0", "level": "AA"} in finding.classifications


async def test_category_and_wcag_criterion_extracted(db_session: AsyncSession, page_result: PageResult) -> None:
    # svg-img-alt: cat.text-alternatives → "text-alternatives", wcag111 → "1.1.1"
    stmt = select(RuleFinding).where(
        RuleFinding.page_result_id == page_result.id,
        RuleFinding.rule_id == "svg-img-alt",
    )
    result = await db_session.execute(stmt)
    finding = result.scalars().first()
    assert finding is not None

    assert finding.category == "text-alternatives"
    assert finding.wcag_criterion == "1.1.1"

    # color-contrast: cat.color → "color", wcag143 → "1.4.3"
    stmt = select(RuleFinding).where(
        RuleFinding.page_result_id == page_result.id,
        RuleFinding.rule_id == "color-contrast",
    )
    result = await db_session.execute(stmt)
    finding = result.scalars().first()
    assert finding is not None

    assert finding.category == "color"
    assert finding.wcag_criterion == "1.4.3"


async def test_reject_missing_url(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    payload = make_axe_payload()
    del payload["testSubject"]

    with pytest.raises(InvalidAxePayloadError, match="URL"):
        await create_page_result(db_session, scan_run.id, payload)


async def test_reject_empty_url(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)

    with pytest.raises(InvalidAxePayloadError, match="URL"):
        await create_page_result(db_session, scan_run.id, make_axe_payload(url=""))


async def test_reject_missing_findings(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)

    with pytest.raises(InvalidAxePayloadError, match="findings"):
        await create_page_result(db_session, scan_run.id, {"testSubject": {"fileName": "https://example.com"}})


@pytest.mark.parametrize(
    ("section", "bad_value"),
    [("violations", "not-a-list"), ("incomplete", 42)],
)
async def test_reject_non_list_finding_section(db_session: AsyncSession, section: str, bad_value: object) -> None:
    scan_run = await make_scan_run_with_parents(db_session)

    payload = make_axe_payload()
    payload["findings"][section] = bad_value

    with pytest.raises(InvalidAxePayloadError, match=section):
        await create_page_result(db_session, scan_run.id, payload)


async def test_reject_rule_missing_required_fields(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)

    with pytest.raises(InvalidAxePayloadError, match="missing required fields"):
        await create_page_result(db_session, scan_run.id, make_axe_payload(violations=[{"id": "some-rule"}]))


async def test_reject_rule_missing_id(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    payload = make_axe_payload(
        violations=[{"impact": "serious", "description": "d", "help": "h", "helpUrl": "u"}],
    )

    with pytest.raises(InvalidAxePayloadError, match="id"):
        await create_page_result(db_session, scan_run.id, payload)


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
