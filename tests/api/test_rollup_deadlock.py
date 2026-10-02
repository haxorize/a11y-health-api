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
from collections.abc import Iterator
from contextlib import AsyncExitStack
from typing import NamedTuple

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.pool import QueuePool

from a11y_health.core.database import SessionSource, bind_session_source
from a11y_health.models.enums import ScoreSnapshotOwnerType
from a11y_health.models.org_unit import OrgUnit
from a11y_health.services import owner as owner_service
from a11y_health.services.owner import ChildrenRead
from tests.factories import (
    SessionFactory,
    assert_error,
    backend_pid,
    cancel_tasks,
    finished_or_blocked,
    make_org_unit,
    substitute_children_read,
)

pytestmark = pytest.mark.integration

# Past the holder's 10s deadlock_timeout below, so a cycle the holder is left
# to detect fails as its 40P01 rather than as a timeout here.
_DEADLINE = 15.0


# The request must run the production `get_db` — fresh session per request,
# commit on success, rollback on exception — just bound to the test engine.
@pytest.fixture
def _requests_on_the_test_engine(engine: AsyncEngine) -> Iterator[None]:
    with bind_session_source(SessionSource(engine)):
        yield


class _Race(NamedTuple):
    response: Response
    setup: AsyncSession
    holder: AsyncSession
    child: OrgUnit
    grandchild: OrgUnit


async def _race_a_reparent_into_a_deadlock(
    client: AsyncClient, committed_session_factory: SessionFactory, mocker
) -> _Race:
    setup = committed_session_factory()
    root = await make_org_unit(setup, name="Humana")
    child = await make_org_unit(setup, name="CenterWell", parent_id=root.id)
    grandchild = await make_org_unit(setup, name="Primary Care", parent_id=child.id)
    await setup.commit()

    holder = committed_session_factory()
    poll = committed_session_factory()

    # Postgres arms a waiter's deadlock check once, deadlock_timeout after the
    # wait begins, and never re-arms it — so the victim's check must start
    # after the cycle is closed. Pausing the reparent's old-parent rollup
    # between its child-lock grant and the root cascade lets the holder queue
    # on the child first; the request then blocks on root as the cycle's last
    # waiter, and its one-shot check (engine-wide 50ms, conftest) always finds
    # the closed cycle. The holder's own check is pushed out of the way, for
    # its transaction only, so the raise never returns to the pool with it.
    await holder.execute(text("SET LOCAL deadlock_timeout = '10s'"))
    await owner_service._acquire_rollup_lock(holder, ScoreSnapshotOwnerType.ORG_UNIT, root.id)
    holder_pid = await backend_pid(holder)

    request_holds_child = asyncio.Event()
    holder_queued_on_child = asyncio.Event()

    def pause_on_child(read_children: ChildrenRead) -> ChildrenRead:
        async def pause_after_child_read(session: AsyncSession, owner_id: int) -> list:
            children = await read_children(session, owner_id)
            if owner_id == child.id and not holder_queued_on_child.is_set():
                request_holds_child.set()
                await holder_queued_on_child.wait()
            return children

        return pause_after_child_read

    substitute_children_read(mocker, ScoreSnapshotOwnerType.ORG_UNIT, pause_on_child)

    async def reparent() -> Response:
        return await client.patch(f"/api/v1/org-units/{grandchild.id}", json={"parent_id": root.id})

    request = asyncio.create_task(reparent())
    holder_acquire: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(request_holds_child.wait(), timeout=_DEADLINE)

        holder_acquire = asyncio.create_task(
            owner_service._acquire_rollup_lock(holder, ScoreSnapshotOwnerType.ORG_UNIT, child.id)
        )

        # Fails fast if a regression drops the per-owner lock and lets the
        # holder acquire without ever waiting.
        blocked = await finished_or_blocked(poll, holder_acquire, holder_pid, locktype="advisory")
        assert blocked, "holder acquired the child lock without blocking on the rollup lock"

        # Resuming closes the cycle. The request aborts with 40P01 and the
        # holder's acquisition is granted — returning cleanly is itself the
        # assertion that the holder was not the victim.
        holder_queued_on_child.set()
        await asyncio.wait_for(holder_acquire, timeout=_DEADLINE)
        response = await asyncio.wait_for(request, timeout=_DEADLINE)
    finally:
        await cancel_tasks(request, holder_acquire)

    return _Race(response, setup, holder, child, grandchild)


@pytest.mark.usefixtures("_requests_on_the_test_engine")
async def test_a_genuine_deadlock_loser_returns_the_retryable_409_through_the_full_stack(
    client: AsyncClient, committed_session_factory: SessionFactory, mocker
) -> None:
    race = await _race_a_reparent_into_a_deadlock(client, committed_session_factory, mocker)

    assert_error(race.response, 409, "concurrent_rollup", message_contains="retry")

    # get_db rolled the poisoned transaction back: the reparent never persisted.
    await race.setup.refresh(race.grandchild)
    assert race.grandchild.parent_id == race.child.id


# The holder's raised timeout must end with its transaction, not ride its
# connection back into the pool, where a later deadlock test's waiter would arm
# a 10s check instead of 50ms. A plain SET the holder then commits turns this
# red; one it rolls back does not.
@pytest.mark.usefixtures("_requests_on_the_test_engine")
async def test_the_race_leaves_every_pooled_connection_at_the_engine_deadlock_timeout(
    client: AsyncClient, committed_session_factory: SessionFactory, mocker, engine: AsyncEngine
) -> None:
    race = await _race_a_reparent_into_a_deadlock(client, committed_session_factory, mocker)
    holder_pid = await backend_pid(race.holder)
    await race.holder.close()

    pool = engine.pool
    assert isinstance(pool, QueuePool)
    async with AsyncExitStack() as stack:
        connections = [await stack.enter_async_context(engine.connect()) for _ in range(pool.checkedin())]
        read = [
            (await conn.execute(text("SELECT pg_backend_pid(), current_setting('deadlock_timeout')"))).one()
            for conn in connections
        ]

    assert holder_pid in {pid for pid, _ in read}
    assert {timeout for _, timeout in read} == {"50ms"}
