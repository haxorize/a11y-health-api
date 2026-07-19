import pytest
from sqlalchemy import text
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_page_result, make_rule_finding, make_scan_run_with_parents


async def test_out_of_vocabulary_classification_is_refused_at_flush(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)

    with pytest.raises(StatementError):
        await make_rule_finding(db_session, page_result_id=page.id, classifications=[{"standard": "section508"}])


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
