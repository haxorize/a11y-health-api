import logging
import re
from typing import Any, get_args

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import NotFoundError
from a11y_health.models.classification import Classification, ClassificationToken, token_to_stored_classification
from a11y_health.models.enums import Category, Impact, ScanRunStatus
from a11y_health.models.rule_finding import RuleFinding
from a11y_health.schemas.rule_finding import FindingFilters
from a11y_health.services import rule_finding as rule_finding_service
from tests.factories import (
    make_node_finding,
    make_page_result,
    make_page_result_with_parents,
    make_rule_finding,
    make_scan_run_with_parents,
)
from tests.finding_filter_cases import FILTER_CASES, FilterCase


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


@pytest.mark.parametrize("case", FILTER_CASES)
async def test_node_finding_count_present_under_each_filter(db_session: AsyncSession, case: FilterCase) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    match = await make_rule_finding(db_session, page_result_id=page.id, rule_id="image-alt", **case.matching[0])
    await make_node_finding(db_session, rule_finding_id=match.id)
    await make_node_finding(db_session, rule_finding_id=match.id)
    other = await make_rule_finding(db_session, page_result_id=page.id, rule_id="meta-viewport", **case.other)
    await make_node_finding(db_session, rule_finding_id=other.id)

    result = await rule_finding_service.list_findings(db_session, scan_run.id, filters=FindingFilters(**case.filters))

    assert [(f.rule_id, f.node_finding_count) for f in result.items] == [("image-alt", 2)]


@pytest.mark.parametrize("case", FILTER_CASES)
async def test_total_counts_only_findings_matching_the_filter(db_session: AsyncSession, case: FilterCase) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page_result = await make_page_result(db_session, scan_run_id=scan_run.id)
    for rule_id in ("image-alt", "aria-hidden-focus"):
        await make_rule_finding(db_session, page_result_id=page_result.id, rule_id=rule_id, **case.matching[0])
    await make_rule_finding(db_session, page_result_id=page_result.id, rule_id="meta-viewport", **case.other)

    result = await rule_finding_service.list_findings(
        db_session, scan_run.id, filters=FindingFilters(**case.filters), limit=1
    )

    # limit=1 keeps the page smaller than the match set, so total can only come
    # from the filtered count, never from the returned items.
    assert len(result.items) == 1
    assert result.total == 2


# Breaks when a dimension matches all of its selected values, or only the first,
# instead of any of them.
@pytest.mark.parametrize("case", FILTER_CASES)
async def test_each_filter_matches_any_selected_value(db_session: AsyncSession, case: FilterCase) -> None:
    page = await make_page_result_with_parents(db_session)
    kept = await case.seed(db_session, page.id)

    result = await rule_finding_service.list_findings(
        db_session, page.scan_run_id, filters=FindingFilters(**case.filters)
    )

    assert {f.rule_id for f in result.items} == kept


async def test_filter_dimensions_combine_with_and(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    await make_rule_finding(
        db_session, page_result_id=page.id, impact=Impact.CRITICAL, category=Category.COLOR, rule_id="color-contrast"
    )
    await make_rule_finding(
        db_session, page_result_id=page.id, impact=Impact.CRITICAL, category=Category.KEYBOARD, rule_id="tabindex"
    )
    await make_rule_finding(
        db_session, page_result_id=page.id, impact=Impact.MINOR, category=Category.COLOR, rule_id="meta-viewport"
    )

    result = await rule_finding_service.list_findings(
        db_session, scan_run.id, filters=FindingFilters(impact=[Impact.CRITICAL], category=[Category.COLOR])
    )

    assert [f.rule_id for f in result.items] == ["color-contrast"]


@pytest.mark.parametrize("token", ["wcag2aa", "wcag21aa"])
async def test_classification_filter_matches_a_finding_by_any_of_its_classifications(
    db_session: AsyncSession, token: ClassificationToken
) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    await make_rule_finding(
        db_session,
        page_result_id=page.id,
        rule_id="color-contrast",
        classifications=[token_to_stored_classification("wcag2aa"), token_to_stored_classification("wcag21aa")],
    )

    result = await rule_finding_service.list_findings(
        db_session, scan_run.id, filters=FindingFilters(classification=[token])
    )

    assert [f.rule_id for f in result.items] == ["color-contrast"]


async def test_total_scoped_to_the_run(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page_result = await make_page_result(db_session, scan_run_id=scan_run.id)
    await make_rule_finding(db_session, page_result_id=page_result.id)
    other_run = await make_scan_run_with_parents(db_session, app_name="Other App", slug="other-app")
    other_page_result = await make_page_result(db_session, scan_run_id=other_run.id)
    await make_rule_finding(db_session, page_result_id=other_page_result.id)

    result = await rule_finding_service.list_findings(db_session, scan_run.id)

    assert [f.page_result_id for f in result.items] == [page_result.id]
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
    assert options.classifications == []


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


async def test_filter_options_enumerate_distinct_classifications_in_vocabulary_order(
    db_session: AsyncSession,
) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page_one = await make_page_result(db_session, scan_run_id=scan_run.id, url="https://example.com/a")
    page_two = await make_page_result(db_session, scan_run_id=scan_run.id, url="https://example.com/b")
    await make_rule_finding(
        db_session,
        page_result_id=page_one.id,
        rule_id="color-contrast",
        classifications=[token_to_stored_classification("best-practice"), token_to_stored_classification("wcag22aaa")],
    )
    await make_rule_finding(
        db_session,
        page_result_id=page_two.id,
        rule_id="image-alt",
        classifications=[token_to_stored_classification("wcag22aaa"), token_to_stored_classification("wcag2a")],
    )

    options = await rule_finding_service.list_filter_options(db_session, scan_run.id)

    assert [(o.token, o.classification) for o in options.classifications] == [
        ("wcag2a", Classification(standard="wcag", version="2.0", level="A")),
        ("wcag22aaa", Classification(standard="wcag", version="2.2", level="AAA")),
        ("best-practice", Classification(standard="best-practice")),
    ]


async def test_filter_options_classifications_scoped_to_the_run(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    other_run = await make_scan_run_with_parents(db_session, org_name="Other Org", app_name="Other App", slug="other")
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    other_page = await make_page_result(db_session, scan_run_id=other_run.id)
    await make_rule_finding(
        db_session, page_result_id=page.id, classifications=[token_to_stored_classification("wcag2aa")]
    )
    await make_rule_finding(
        db_session, page_result_id=other_page.id, classifications=[token_to_stored_classification("best-practice")]
    )

    options = await rule_finding_service.list_filter_options(db_session, scan_run.id)

    assert [o.token for o in options.classifications] == ["wcag2aa"]


async def test_filter_options_omit_valid_but_off_vocabulary_classification(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    # A stored entry that validates as a Classification without naming any
    # token (e.g. a raw-backfilled WCAG 3.0) earns no option, with a warning,
    # instead of failing the enumeration; the why is `classification_options`'
    # docstring (models/classification.py).
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    await make_rule_finding(
        db_session,
        page_result_id=page.id,
        classifications=[
            {"standard": "wcag", "version": "3.0", "level": "A"},
            token_to_stored_classification("wcag2aa"),
        ],
    )

    with caplog.at_level(logging.WARNING):
        options = await rule_finding_service.list_filter_options(db_session, scan_run.id)

    assert [o.token for o in options.classifications] == ["wcag2aa"]
    assert "3.0" in caplog.text


async def test_filter_options_statements_are_bounded_by_the_vocabulary_not_the_findings(
    db_session: AsyncSession,
) -> None:
    # Reds if the read pulls one row per Rule Finding back into Python: the top
    # node's estimate then tracks the 2,000 seeded rows, not the vocabulary.
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    seed = await make_rule_finding(db_session, page_result_id=page.id)
    columns = ", ".join(c.name for c in RuleFinding.__table__.columns if c.name != "id")
    await db_session.execute(
        text(
            f"INSERT INTO rule_finding ({columns}) "  # noqa: S608 — column names from the model
            f"SELECT {columns} FROM rule_finding, generate_series(1, 2000) WHERE id = :id"
        ),
        {"id": seed.id},
    )
    # Unanalyzed, page_result's side of the join estimates near zero rows and
    # hides the growth this test exists to see.
    await db_session.execute(text("ANALYZE rule_finding, page_result"))
    statements: list[tuple[str, Any]] = []
    connection = (await db_session.connection()).sync_connection
    assert connection is not None

    def record(_conn: object, _cursor: object, statement: str, parameters: Any, *_: object) -> None:
        statements.append((statement, parameters))

    event.listen(connection, "before_cursor_execute", record)
    try:
        await rule_finding_service.list_filter_options(db_session, scan_run.id)
    finally:
        event.remove(connection, "before_cursor_execute", record)

    over_findings = [(s, p) for s, p in statements if re.search(r"\bFROM rule_finding\b", s)]
    assert over_findings
    for statement, parameters in over_findings:
        explained = await (await db_session.connection()).exec_driver_sql(
            f"EXPLAIN (FORMAT JSON) {statement}", parameters
        )
        top = explained.scalar_one()[0]["Plan"]
        assert top["Plan Rows"] <= len(get_args(ClassificationToken)), statement


async def test_filter_options_warn_once_per_distinct_invalid_classification(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    for _ in range(3):
        finding = await make_rule_finding(db_session, page_result_id=page.id)
        await db_session.execute(
            text("UPDATE rule_finding SET classifications = CAST(:val AS jsonb) WHERE id = :id"),
            {
                "val": '[{"standard": "section508"}, {"standard": "wcag", "version": "2.1", "level": "AA"}]',
                "id": finding.id,
            },
        )
    scan_run_id = scan_run.id
    db_session.expire_all()

    with caplog.at_level(logging.WARNING):
        options = await rule_finding_service.list_filter_options(db_session, scan_run_id)

    assert [o.token for o in options.classifications] == ["wcag21aa"]
    assert len([r for r in caplog.records if "section508" in r.getMessage()]) == 1


async def test_filter_options_skip_a_non_array_value(db_session: AsyncSession) -> None:
    # The column carries no shape constraint (ADR 0014), so a raw write can
    # leave an object where the array belongs; the expansion must skip it
    # rather than fail the whole read.
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    await make_rule_finding(db_session, page_result_id=page.id, wcag_criteria=["1.4.3"])
    broken = await make_rule_finding(db_session, page_result_id=page.id)
    await db_session.execute(
        text("UPDATE rule_finding SET wcag_criteria = '{}'::jsonb, classifications = '{}'::jsonb WHERE id = :id"),
        {"id": broken.id},
    )

    options = await rule_finding_service.list_filter_options(db_session, scan_run.id)

    assert options.wcag_criteria == ["1.4.3"]
    assert [o.token for o in options.classifications] == ["wcag2aa"]


async def test_pinning_the_classification_filter_emits_one_containment_per_token(db_session: AsyncSession) -> None:
    # Pins the SQL the classification filter emitted before the predicate moved
    # to the column's module: an OR of @> tests, each against a one-entry array
    # in the compact stored shape, so the GIN index keeps serving it.
    scan_run = await make_scan_run_with_parents(db_session)
    statements: list[tuple[str, Any]] = []
    connection = (await db_session.connection()).sync_connection
    assert connection is not None

    def record(_conn: object, _cursor: object, statement: str, parameters: Any, *_: object) -> None:
        statements.append((statement, parameters))

    event.listen(connection, "before_cursor_execute", record)
    try:
        await rule_finding_service.list_findings(
            db_session, scan_run.id, filters=FindingFilters(classification=["wcag2aa", "best-practice"])
        )
    finally:
        event.remove(connection, "before_cursor_execute", record)

    containment = r"\(rule_finding\.classifications @> \$(\d+)::JSONB\)"
    fragment = re.compile(rf"\({containment} OR {containment}\)")
    filtered = [(fragment.search(s), p) for s, p in statements if "@>" in s]
    assert filtered
    for match, parameters in filtered:
        assert match is not None
        assert [parameters[int(n) - 1] for n in match.groups()] == [
            '[{"standard": "wcag", "version": "2.0", "level": "AA"}]',
            '[{"standard": "best-practice"}]',
        ]


async def test_planted_invalid_classification_is_dropped_from_reads_not_fatal(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    # A raw-SQL backfill bypasses the column's bind-time guard; the read must
    # drop the invalid entry (with a warning) instead of 500ing the page (#106).
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
