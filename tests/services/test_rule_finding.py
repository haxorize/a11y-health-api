from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.enums import Category, FindingType, Impact, ScanRunStatus
from a11y_health.services import rule_finding as rule_finding_service
from tests.factories import (
    make_node_finding,
    make_page_result,
    make_rule_finding,
    make_scan_run_with_parents,
)


async def test_node_finding_count_reflects_rows_at_read_time_on_pending_run(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session, status=ScanRunStatus.PENDING)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    finding = await make_rule_finding(db_session, page_result_id=page.id)
    await make_node_finding(db_session, rule_finding_id=finding.id)

    first = await rule_finding_service.list_findings(db_session, scan_run.id)
    await make_node_finding(db_session, rule_finding_id=finding.id)
    second = await rule_finding_service.list_findings(db_session, scan_run.id)

    assert first.items[0].node_finding_count == 1
    assert second.items[0].node_finding_count == 2


async def test_node_finding_count_zero_for_finding_with_no_node_findings(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    await make_rule_finding(db_session, page_result_id=page.id)

    result = await rule_finding_service.list_findings(db_session, scan_run.id)

    assert result.items[0].node_finding_count == 0


@pytest.mark.parametrize(
    ("match_kwargs", "other_kwargs", "filter_kwargs"),
    [
        pytest.param(
            {"finding_type": FindingType.VIOLATION},
            {"finding_type": FindingType.INCOMPLETE},
            {"finding_type": [FindingType.VIOLATION]},
            id="finding_type",
        ),
        pytest.param(
            {"impact": Impact.CRITICAL},
            {"impact": Impact.MINOR},
            {"impact": [Impact.CRITICAL]},
            id="impact",
        ),
        pytest.param(
            {"category": Category.KEYBOARD},
            {"category": Category.COLOR},
            {"category": [Category.KEYBOARD]},
            id="category",
        ),
        pytest.param(
            {"wcag_criteria": ["2.4.4"]},
            {"wcag_criteria": ["1.4.3"]},
            {"wcag_criterion": ["2.4.4"]},
            id="wcag_criterion",
        ),
        pytest.param(
            {"classifications": [{"standard": "best-practice"}]},
            {"classifications": [{"standard": "wcag", "version": "2.0", "level": "AA"}]},
            {"classification": ["best-practice"]},
            id="classification",
        ),
    ],
)
async def test_node_finding_count_present_under_each_filter(
    db_session: AsyncSession,
    match_kwargs: dict[str, Any],
    other_kwargs: dict[str, Any],
    filter_kwargs: dict[str, Any],
) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    match = await make_rule_finding(db_session, page_result_id=page.id, rule_id="image-alt", **match_kwargs)
    await make_node_finding(db_session, rule_finding_id=match.id)
    await make_node_finding(db_session, rule_finding_id=match.id)
    other = await make_rule_finding(db_session, page_result_id=page.id, rule_id="meta-viewport", **other_kwargs)
    await make_node_finding(db_session, rule_finding_id=other.id)

    result = await rule_finding_service.list_findings(db_session, scan_run.id, **filter_kwargs)

    assert [(f.rule_id, f.node_finding_count) for f in result.items] == [("image-alt", 2)]
