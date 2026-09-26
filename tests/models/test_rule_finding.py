import logging

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.classification import Classification, token_to_stored_classification
from a11y_health.models.rule_finding import RuleFinding
from tests.factories import make_page_result_with_parents, make_rule_finding


async def test_unknown_standard_classification_is_refused_at_flush(db_session: AsyncSession) -> None:
    page = await make_page_result_with_parents(db_session)

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
    page = await make_page_result_with_parents(db_session)

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
    page = await make_page_result_with_parents(db_session)
    rf = await make_rule_finding(
        db_session, page_result_id=page.id, classifications=[token_to_stored_classification("best-practice")]
    )

    # Null members must be dropped from the target before @> runs: the stored
    # row has no "version"/"level" keys, so an uncompacted target can't match.
    stmt = select(RuleFinding.id).where(
        RuleFinding.classifications.contains([{"standard": "best-practice", "version": None, "level": None}])
    )

    assert (await db_session.execute(stmt)).scalars().all() == [rf.id]


async def test_a_loaded_rule_finding_carries_classifications(db_session: AsyncSession) -> None:
    page = await make_page_result_with_parents(db_session)
    rf = await make_rule_finding(
        db_session, page_result_id=page.id, classifications=[{"standard": "wcag", "version": "2.1", "level": "AA"}]
    )
    rf_id = rf.id
    db_session.expire_all()

    loaded = await db_session.get_one(RuleFinding, rf_id)

    assert loaded.classifications == [Classification(standard="wcag", version="2.1", level="AA")]


async def test_an_invalid_entry_written_past_the_orm_is_dropped_on_read(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    page = await make_page_result_with_parents(db_session)
    rf = await make_rule_finding(db_session, page_result_id=page.id)
    await db_session.execute(
        text("UPDATE rule_finding SET classifications = CAST(:val AS jsonb) WHERE id = :id"),
        {"val": '[{"standard": "section508"}, {"standard": "best-practice", "version": null}]', "id": rf.id},
    )
    rf_id = rf.id
    db_session.expire_all()

    with caplog.at_level(logging.WARNING):
        loaded = await db_session.get_one(RuleFinding, rf_id)

    assert loaded.classifications == [Classification(standard="best-practice")]
    assert "section508" in caplog.text


async def test_bound_entries_are_stored_in_the_compact_shape(db_session: AsyncSession) -> None:
    page = await make_page_result_with_parents(db_session)

    rf = await make_rule_finding(
        db_session,
        page_result_id=page.id,
        classifications=[{"standard": "best-practice", "version": None, "level": None}],
    )

    stored = (
        await db_session.execute(text("SELECT classifications FROM rule_finding WHERE id = :id"), {"id": rf.id})
    ).scalar_one()
    assert stored == [{"standard": "best-practice"}]
