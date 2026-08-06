import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.classification import token_to_stored_classification
from a11y_health.models.rule_finding import RuleFinding
from tests.factories import make_page_result, make_rule_finding, make_scan_run_with_parents


async def test_unknown_standard_classification_is_refused_at_flush(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)

    with pytest.raises(StatementError):
        await make_rule_finding(db_session, page_result_id=page.id, classifications=[{"standard": "section508"}])


@pytest.mark.parametrize(
    "entry",
    [
        pytest.param({"standard": "wcag", "version": "2.1", "level": "AA", "note": "waived"}, id="extra-member"),
        pytest.param({"standard": "wcag"}, id="wcag-without-version-and-level"),
        pytest.param({"standard": "best-practice", "level": "AA"}, id="best-practice-with-level"),
    ],
)
async def test_non_canonical_classification_is_refused_at_flush(
    db_session: AsyncSession, entry: dict[str, str]
) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)

    with pytest.raises(StatementError):
        await make_rule_finding(db_session, page_result_id=page.id, classifications=[entry])


async def test_invalid_containment_target_is_refused_at_query_time(db_session: AsyncSession) -> None:
    # Containment targets hit the bind-time guard only because the ORM coerces
    # .contains() operands to the column type — the unpinned default behind the
    # ADR 0031 amendment's coverage claim. If coercion changes, this fails
    # loudly.
    with pytest.raises(StatementError):
        await db_session.execute(
            select(RuleFinding.id).where(RuleFinding.classifications.contains([{"standard": "wcag"}]))
        )


async def test_containment_target_is_compacted_before_comparison(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    rf = await make_rule_finding(
        db_session, page_result_id=page.id, classifications=[token_to_stored_classification("best-practice")]
    )

    # Null members must be dropped from the target before @> runs: the stored
    # row has no "version"/"level" keys, so an uncompacted target can't match.
    stmt = select(RuleFinding.id).where(
        RuleFinding.classifications.contains([{"standard": "best-practice", "version": None, "level": None}])
    )

    assert (await db_session.execute(stmt)).scalars().all() == [rf.id]


async def test_bound_entries_are_stored_in_the_compact_shape(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)

    rf = await make_rule_finding(
        db_session,
        page_result_id=page.id,
        classifications=[{"standard": "best-practice", "version": None, "level": None}],
    )

    stored = (
        await db_session.execute(text("SELECT classifications FROM rule_finding WHERE id = :id"), {"id": rf.id})
    ).scalar_one()
    assert stored == [{"standard": "best-practice"}]
