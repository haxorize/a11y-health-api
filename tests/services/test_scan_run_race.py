"""Two-session coverage for the Scan Run row lock (#178, ADR 0048).

Each test leaves one session's write to a Scan Run uncommitted, runs a
second session's write against the same run, and records whether the second
was waiting on a lock when the first committed. The first App deletion race
instead pauses completion right after its Scan Run lock, so the deletion runs
into it mid-operation. Real commits on separate connections
(`committed_session_factory`) put the two in separate transactions that
contend on real locks, each reading only what the other has committed.
"""

import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core import existence
from a11y_health.core.exceptions import InvalidStatusTransitionError, NotFoundError, ScanRunCompletedError
from a11y_health.models.app import App
from a11y_health.models.enums import ScanRunStatus
from a11y_health.models.page_result import PageResult
from a11y_health.models.scan_run import ScanRun
from a11y_health.schemas.scan_run import ScanRunStatusUpdate
from a11y_health.services import app as app_service
from a11y_health.services import page_result as page_result_service
from a11y_health.services import scan_run as scan_run_service
from tests.factories import (
    RACE_DEADLINE,
    SessionFactory,
    backend_pid,
    cancel_tasks,
    finished_or_blocked,
    make_axe_payload,
    make_scan_run_with_parents,
    race_behind_open_transaction,
)

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


# Reds at the refusal when Page Result creation reads the run unlocked, or
# keeps the instance loaded before the completion committed: either way it
# still waits, since its foreign-key check takes KEY SHARE, which completion's
# FOR UPDATE blocks, and then inserts the page.
async def test_a_page_result_created_mid_completion_waits_and_is_refused(
    committed_session_factory: SessionFactory,
) -> None:
    setup, scan_run_id = await _pending_run_with_one_page(committed_session_factory)

    async def complete(session: AsyncSession) -> None:
        await scan_run_service.update_scan_run_status(session, scan_run_id, _COMPLETE)

    async def read_then_create_page_result(session: AsyncSession) -> None:
        # An ingest session read the run as Pending on its earlier pages; bound
        # for the reason the completion race gives.
        loaded = await session.get(ScanRun, scan_run_id)
        await page_result_service.create_page_result(
            session, scan_run_id, make_axe_payload(url="https://example.com/2")
        )
        assert loaded is not None

    waited, outcome = await race_behind_open_transaction(
        committed_session_factory, complete, read_then_create_page_result
    )

    assert waited
    assert isinstance(outcome, ScanRunCompletedError)
    assert await _page_count(setup, scan_run_id) == 1


# Reds at `waited` when Page Result creation locks the run exclusively.
async def test_concurrent_page_result_creations_do_not_wait_on_each_other(
    committed_session_factory: SessionFactory,
) -> None:
    setup, scan_run_id = await _pending_run_with_one_page(committed_session_factory)

    def create_page_result(url: str):
        async def create(session: AsyncSession) -> None:
            await page_result_service.create_page_result(session, scan_run_id, make_axe_payload(url=url))

        return create

    waited, outcome = await race_behind_open_transaction(
        committed_session_factory,
        create_page_result("https://example.com/2"),
        create_page_result("https://example.com/3"),
    )

    assert not waited
    assert outcome is None
    assert await _page_count(setup, scan_run_id) == 3


# Reds with an IntegrityError on the page's foreign key when Page Result
# creation reads the run without a lock.
async def test_a_page_result_created_mid_delete_waits_and_is_not_found(
    committed_session_factory: SessionFactory,
) -> None:
    _, scan_run_id = await _pending_run_with_one_page(committed_session_factory)

    async def delete(session: AsyncSession) -> None:
        await scan_run_service.delete_scan_run(session, scan_run_id)

    async def create_page_result(session: AsyncSession) -> None:
        await page_result_service.create_page_result(
            session, scan_run_id, make_axe_payload(url="https://example.com/2")
        )

    waited, outcome = await race_behind_open_transaction(committed_session_factory, delete, create_page_result)

    assert waited
    assert isinstance(outcome, NotFoundError)
    assert str(outcome) == f"Scan run {scan_run_id} not found"


# Reds with a 40P01 on completion's App Score Snapshot insert when completion
# locks the Scan Run before the App: the deletion holds the App row and waits
# on the run in its cascade, and the insert's key check waits on the App.
async def test_an_app_deleted_mid_completion_waits_for_it(committed_session_factory: SessionFactory, mocker) -> None:
    setup, scan_run_id = await _pending_run_with_one_page(committed_session_factory)
    app_id = (await scan_run_service.get_scan_run(setup, scan_run_id)).app_id
    await setup.rollback()
    completing = committed_session_factory()
    deleting = committed_session_factory()
    poll = committed_session_factory()

    run_locked = asyncio.Event()
    resume = asyncio.Event()
    real_lock_by_pk = existence.lock_by_pk

    async def pause_after_lock(session: AsyncSession, model: type[ScanRun], locked_id: int, *, shared: bool) -> ScanRun:
        scan_run = await real_lock_by_pk(session, model, locked_id, shared=shared)
        run_locked.set()
        await resume.wait()
        return scan_run

    mocker.patch.object(existence, "lock_by_pk", pause_after_lock)

    async def complete() -> None:
        await scan_run_service.update_scan_run_status(completing, scan_run_id, _COMPLETE)
        await completing.commit()

    async def delete() -> None:
        await app_service.delete_app(deleting, app_id)
        await deleting.commit()

    completion = asyncio.create_task(complete())
    deletion: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(run_locked.wait(), timeout=RACE_DEADLINE)
        deleting_pid = await backend_pid(deleting)
        deletion = asyncio.create_task(delete())
        assert await finished_or_blocked(poll, deletion, deleting_pid)
        resume.set()
        await asyncio.wait_for(completion, timeout=RACE_DEADLINE)
        await asyncio.wait_for(deletion, timeout=RACE_DEADLINE)
    finally:
        await cancel_tasks(completion, deletion)

    assert await setup.get(App, app_id) is None


# The other order: completion waits on the App the deletion holds, and finds
# the run gone with it.
async def test_a_completion_behind_an_app_deletion_waits_and_is_not_found(
    committed_session_factory: SessionFactory,
) -> None:
    setup, scan_run_id = await _pending_run_with_one_page(committed_session_factory)
    app_id = (await scan_run_service.get_scan_run(setup, scan_run_id)).app_id
    await setup.rollback()

    async def delete(session: AsyncSession) -> None:
        await app_service.delete_app(session, app_id)

    async def complete(session: AsyncSession) -> None:
        await scan_run_service.update_scan_run_status(session, scan_run_id, _COMPLETE)

    waited, outcome = await race_behind_open_transaction(committed_session_factory, delete, complete)

    assert waited
    assert isinstance(outcome, NotFoundError)
    assert str(outcome) == f"Scan run {scan_run_id} not found"
