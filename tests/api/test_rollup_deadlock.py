"""The #104 deadlock 409, pinned through the full request stack (#110).

The per-operation transport tests raise `ConcurrentRollupError` from a mock, so
their request transaction stays healthy; only a genuine 40P01 leaves the
session poisoned when `get_db`'s rollback and the `DomainError` handler run.
This test drives a real two-transaction lock cycle (ADR 0029) through HTTP so
a handler or teardown that touches the session after the deadlock fails here
instead of in production. Real per-request sessions and real commits are
required, so ADR 0011's rollback isolation cannot apply — data is committed
and `committed_session_factory`'s teardown truncates.
"""

import asyncio

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from a11y_health.core import database
from a11y_health.models.enums import ScoreSnapshotOwnerType
from a11y_health.services import score_snapshot as score_snapshot_service
from tests.factories import SessionFactory, advisory_lock_waiters, assert_error, make_org_unit

pytestmark = pytest.mark.integration

_DEADLINE = 15.0


async def test_a_genuine_deadlock_loser_returns_the_retryable_409_through_the_full_stack(
    client: AsyncClient,
    engine: AsyncEngine,
    committed_session_factory: SessionFactory,
    mocker,
) -> None:
    setup = committed_session_factory()
    root = await make_org_unit(setup, name="Humana")
    child = await make_org_unit(setup, name="CenterWell", parent_id=root.id)
    grandchild = await make_org_unit(setup, name="Primary Care", parent_id=child.id)
    await setup.commit()

    # The request must run the production `get_db` — fresh session per request,
    # commit on success, rollback on exception — just bound to the test engine.
    mocker.patch.object(database, "async_session", async_sessionmaker(engine, expire_on_commit=False))

    holder = committed_session_factory()
    poll = committed_session_factory()

    # Postgres arms a waiter's deadlock check once, deadlock_timeout after the
    # wait begins, and never re-arms it — so the victim's check must start
    # after the cycle is closed. Pausing the reparent's old-parent rollup
    # between its child-lock grant and the root cascade lets the holder queue
    # on the child first; the request then blocks on root as the cycle's last
    # waiter, and its one-shot check (engine-wide 50ms, conftest) always finds
    # the closed cycle. The holder's own check is pushed out of the way.
    await holder.execute(text("SET deadlock_timeout = '10s'"))
    await score_snapshot_service._acquire_rollup_lock(holder, ScoreSnapshotOwnerType.ORG_UNIT, root.id)

    request_holds_child = asyncio.Event()
    holder_queued_on_child = asyncio.Event()
    read_children = score_snapshot_service._latest_child_snapshots

    async def pause_after_child_read(session: AsyncSession, owner_id: int) -> list:
        children = await read_children(session, owner_id)
        if owner_id == child.id and not holder_queued_on_child.is_set():
            request_holds_child.set()
            await holder_queued_on_child.wait()
        return children

    mocker.patch.object(score_snapshot_service, "_latest_child_snapshots", pause_after_child_read)

    async def reparent() -> Response:
        return await client.patch(f"/api/v1/org-units/{grandchild.id}", json={"parent_id": root.id})

    request = asyncio.create_task(reparent())
    holder_acquire: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(request_holds_child.wait(), timeout=_DEADLINE)

        holder_acquire = asyncio.create_task(
            score_snapshot_service._acquire_rollup_lock(holder, ScoreSnapshotOwnerType.ORG_UNIT, child.id)
        )

        # The done() guard fails fast if a regression drops the per-owner lock
        # and lets the holder acquire without ever waiting.
        async def holder_blocked() -> None:
            while not holder_acquire.done() and await advisory_lock_waiters(poll) == 0:  # noqa: ASYNC110
                await asyncio.sleep(0.025)

        await asyncio.wait_for(holder_blocked(), timeout=_DEADLINE)
        await poll.rollback()
        assert not holder_acquire.done(), "holder acquired the child lock without blocking on the rollup lock"

        # Resuming closes the cycle. The request aborts with 40P01 and the
        # holder's acquisition is granted — returning cleanly is itself the
        # assertion that the holder was not the victim.
        holder_queued_on_child.set()
        await asyncio.wait_for(holder_acquire, timeout=_DEADLINE)
        response = await asyncio.wait_for(request, timeout=_DEADLINE)
    finally:
        tasks = [task for task in (request, holder_acquire) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    assert_error(response, 409, "concurrent_rollup", message_contains="retry")

    # get_db rolled the poisoned transaction back: the reparent never persisted.
    await setup.refresh(grandchild)
    assert grandchild.parent_id == child.id
