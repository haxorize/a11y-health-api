import logging
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import NotFoundError
from a11y_health.models.classification import Classification
from a11y_health.models.enums import Category, FindingType, Impact, ScanRunStatus
from a11y_health.schemas._tag_parsing import token_to_stored_classification
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


# One case per filter dimension: factory kwargs for a matching finding, for a
# non-matching one, and the service filter that separates them. Shared by every
# per-filter parametrized test so a new dimension can't land in one and not the other.
FILTER_CASES = [
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
        {"classifications": [token_to_stored_classification("best-practice")]},
        {"classifications": [token_to_stored_classification("wcag2aa")]},
        {"classification": ["best-practice"]},
        id="classification",
    ),
]


@pytest.mark.parametrize(("match_kwargs", "other_kwargs", "filter_kwargs"), FILTER_CASES)
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


@pytest.mark.parametrize(("match_kwargs", "other_kwargs", "filter_kwargs"), FILTER_CASES)
async def test_total_counts_only_findings_matching_the_filter(
    db_session: AsyncSession,
    match_kwargs: dict[str, Any],
    other_kwargs: dict[str, Any],
    filter_kwargs: dict[str, Any],
) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page_result = await make_page_result(db_session, scan_run_id=scan_run.id)
    for rule_id in ("image-alt", "aria-hidden-focus"):
        await make_rule_finding(db_session, page_result_id=page_result.id, rule_id=rule_id, **match_kwargs)
    await make_rule_finding(db_session, page_result_id=page_result.id, rule_id="meta-viewport", **other_kwargs)

    result = await rule_finding_service.list_findings(db_session, scan_run.id, limit=1, **filter_kwargs)

    # limit=1 keeps the page smaller than the match set, so total can only come
    # from the filtered count, never from the returned items.
    assert len(result.items) == 1
    assert result.total == 2


async def test_total_scoped_to_the_run(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page_result = await make_page_result(db_session, scan_run_id=scan_run.id)
    await make_rule_finding(db_session, page_result_id=page_result.id)
    other_run = await make_scan_run_with_parents(db_session, app_name="Other App", slug="other-app")
    other_page_result = await make_page_result(db_session, scan_run_id=other_run.id)
    await make_rule_finding(db_session, page_result_id=other_page_result.id)

    result = await rule_finding_service.list_findings(db_session, scan_run.id)

    assert result.total == 1


async def test_filter_options_enumerate_distinct_wcag_criteria(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page_one = await make_page_result(db_session, scan_run_id=scan_run.id, url="https://example.com/a")
    page_two = await make_page_result(db_session, scan_run_id=scan_run.id, url="https://example.com/b")
    await make_rule_finding(
        db_session, page_result_id=page_one.id, rule_id="color-contrast", wcag_criteria=["1.4.3", "1.1.1"]
    )
    await make_rule_finding(
        db_session, page_result_id=page_two.id, rule_id="image-alt", wcag_criteria=["1.1.1", "4.1.2"]
    )

    options = await rule_finding_service.list_filter_options(db_session, scan_run.id)

    assert options.wcag_criteria == ["1.1.1", "1.4.3", "4.1.2"]


async def test_filter_options_scan_run_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await rule_finding_service.list_filter_options(db_session, 999)


async def test_filter_options_empty_for_run_without_findings(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)

    options = await rule_finding_service.list_filter_options(db_session, scan_run.id)

    assert options.wcag_criteria == []


async def test_filter_options_scoped_to_the_run(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    other_run = await make_scan_run_with_parents(db_session, org_name="Other Org", app_name="Other App", slug="other")
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    other_page = await make_page_result(db_session, scan_run_id=other_run.id)
    await make_rule_finding(db_session, page_result_id=page.id, wcag_criteria=["1.4.3"])
    await make_rule_finding(db_session, page_result_id=other_page.id, wcag_criteria=["4.1.2"])

    options = await rule_finding_service.list_filter_options(db_session, scan_run.id)

    assert options.wcag_criteria == ["1.4.3"]


async def test_filter_options_ordered_numerically_not_lexicographically(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    await make_rule_finding(db_session, page_result_id=page.id, wcag_criteria=["1.10.1", "1.4.3", "1.4.13"])

    options = await rule_finding_service.list_filter_options(db_session, scan_run.id)

    assert options.wcag_criteria == ["1.4.3", "1.4.13", "1.10.1"]


async def test_filter_options_sort_malformed_criterion_last(db_session: AsyncSession) -> None:
    # The column carries no format constraint (ADR 0014); a value written past
    # the ingest regex sorts last instead of failing the whole enumeration.
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    await make_rule_finding(db_session, page_result_id=page.id, wcag_criteria=["not-a-criterion", "1.4.3"])

    options = await rule_finding_service.list_filter_options(db_session, scan_run.id)

    assert options.wcag_criteria == ["1.4.3", "not-a-criterion"]


async def test_planted_out_of_vocabulary_classification_is_dropped_from_reads_not_fatal(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    # A raw-SQL backfill bypasses the column's bind-time guard; the read must
    # drop the unknown entry (with a warning) instead of 500ing the page (#106).
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    finding = await make_rule_finding(db_session, page_result_id=page.id)
    await db_session.execute(
        text("UPDATE rule_finding SET classifications = CAST(:val AS jsonb) WHERE id = :id"),
        {
            "val": '[{"standard": "wcag", "version": "2.1", "level": "AA"}, {"standard": "section508"}]',
            "id": finding.id,
        },
    )
    scan_run_id = scan_run.id
    db_session.expire_all()

    with caplog.at_level(logging.WARNING):
        result = await rule_finding_service.list_findings(db_session, scan_run_id)

    assert result.items[0].classifications == [Classification(standard="wcag", version="2.1", level="AA")]
    assert "section508" in caplog.text
