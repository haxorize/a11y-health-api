"""Two-session coverage for the Scan Run row lock (#178, ADR 0048).

Each test leaves one session's write to a Scan Run uncommitted, runs a
second session's write against the same run, and records whether the second
was waiting on a lock when the first committed. Real commits on separate
connections (`committed_session_factory`) are what let the second session
read the state the first has not committed yet.
"""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import InvalidStatusTransitionError, ScanRunCompletedError
from a11y_health.models.enums import ScanRunStatus
from a11y_health.models.page_result import PageResult
from a11y_health.models.scan_run import ScanRun
from a11y_health.schemas.scan_run import ScanRunStatusUpdate
from a11y_health.services import page_result as page_result_service
from a11y_health.services import scan_run as scan_run_service
from tests.factories import SessionFactory, make_axe_payload, make_scan_run_with_parents, race_behind_open_transaction

pytestmark = pytest.mark.integration

_COMPLETE = ScanRunStatusUpdate(status=ScanRunStatus.COMPLETED)


async def _pending_run_with_one_page(committed_session_factory: SessionFactory) -> tuple[AsyncSession, int]:
    setup = committed_session_factory()
    scan_run_id = (await make_scan_run_with_parents(setup)).id
    await page_result_service.create_page_result(setup, scan_run_id, make_axe_payload(url="https://example.com/1"))
    await setup.commit()
    return setup, scan_run_id


async def _page_count(session: AsyncSession, scan_run_id: int) -> int:
    await session.rollback()
    return await session.scalar(select(func.count()).where(PageResult.scan_run_id == scan_run_id)) or 0


# Reds with an IntegrityError on the snapshot's uniqueness when completion
# reads the run unlocked, and the same way when the locked read keeps the
# instance the loser loaded before the winner committed.
async def test_a_second_completion_waits_and_is_refused(committed_session_factory: SessionFactory) -> None:
    _, scan_run_id = await _pending_run_with_one_page(committed_session_factory)

    async def complete(session: AsyncSession) -> None:
        await scan_run_service.update_scan_run_status(session, scan_run_id, _COMPLETE)

    async def read_then_complete(session: AsyncSession) -> None:
        # The loser read the run as Pending earlier in its transaction, as a
        # session that uploaded the pages itself has. Bound, because the
        # identity map holds an unmodified instance weakly.
        loaded = await session.get(ScanRun, scan_run_id)
        await complete(session)
        assert loaded is not None

    waited, outcome = await race_behind_open_transaction(committed_session_factory, complete, read_then_complete)

    assert waited
    assert isinstance(outcome, InvalidStatusTransitionError)


# Reds at `waited` when the page add reads the run without a lock that
# completion's exclusive lock blocks, and with a persisted page when the
# locked read keeps the instance loaded before the completion committed.
async def test_a_page_added_mid_completion_waits_and_is_refused(committed_session_factory: SessionFactory) -> None:
    setup, scan_run_id = await _pending_run_with_one_page(committed_session_factory)

    async def complete(session: AsyncSession) -> None:
        await scan_run_service.update_scan_run_status(session, scan_run_id, _COMPLETE)

    async def read_then_add_page(session: AsyncSession) -> None:
        # An ingest session read the run as Pending on its earlier pages; bound
        # for the reason the completion race gives.
        loaded = await session.get(ScanRun, scan_run_id)
        await page_result_service.create_page_result(
            session, scan_run_id, make_axe_payload(url="https://example.com/2")
        )
        assert loaded is not None

    waited, outcome = await race_behind_open_transaction(committed_session_factory, complete, read_then_add_page)

    assert waited
    assert isinstance(outcome, ScanRunCompletedError)
    assert await _page_count(setup, scan_run_id) == 1


# Reds at `waited` when the page add takes an exclusive lock on the run.
async def test_concurrent_page_adds_do_not_wait_on_each_other(committed_session_factory: SessionFactory) -> None:
    setup, scan_run_id = await _pending_run_with_one_page(committed_session_factory)

    def add_page(url: str):
        async def add(session: AsyncSession) -> None:
            await page_result_service.create_page_result(session, scan_run_id, make_axe_payload(url=url))

        return add

    waited, outcome = await race_behind_open_transaction(
        committed_session_factory, add_page("https://example.com/2"), add_page("https://example.com/3")
    )

    assert not waited
    assert outcome is None
    assert await _page_count(setup, scan_run_id) == 3
