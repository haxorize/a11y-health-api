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
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

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

    # The request backend keeps the 1s default, so once the cycle closes it is
    # always the one whose deadlock check fires — the deterministic victim.
    await holder.execute(text("SET deadlock_timeout = '10s'"))
    await score_snapshot_service._acquire_rollup_lock(holder, ScoreSnapshotOwnerType.ORG_UNIT, root.id)

    async def reparent() -> Response:
        return await client.patch(f"/api/v1/org-units/{grandchild.id}", json={"parent_id": root.id})

    request = asyncio.create_task(reparent())
    try:
        # The reparent's old-parent rollup locks the child, then blocks
        # cascading to root — the advisory waiter is the request's backend.
        # The done() guard fails fast on the actual response if a regression
        # lets the request finish without ever blocking.
        async def request_blocked() -> None:
            while not request.done() and await advisory_lock_waiters(poll) == 0:  # noqa: ASYNC110
                await asyncio.sleep(0.025)

        await asyncio.wait_for(request_blocked(), timeout=_DEADLINE)
        await poll.rollback()

        # Requesting the child's lock closes the cycle. The request aborts with
        # 40P01 and this acquisition is granted — returning cleanly is itself
        # the assertion that the holder was not the victim.
        await asyncio.wait_for(
            score_snapshot_service._acquire_rollup_lock(holder, ScoreSnapshotOwnerType.ORG_UNIT, child.id),
            timeout=_DEADLINE,
        )
        response = await asyncio.wait_for(request, timeout=_DEADLINE)
    finally:
        request.cancel()
        await asyncio.gather(request, return_exceptions=True)

    assert_error(response, 409, "concurrent_rollup", message_contains="retry")

    # get_db rolled the poisoned transaction back: the reparent never persisted.
    await setup.refresh(grandchild)
    assert grandchild.parent_id == child.id
