"""Two-session coverage for per-owner Rollup serialization (#101, ADR 0029).

Most tests drive real sessions on separate connections with real commits
(`committed_session_factory`), reproducing the stale-children-view
interleaving the #98 uniqueness indexes structurally cannot see; the
deadlock test crosses two plain uncommitted sessions instead.
"""

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pytest
from pytest import approx
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from a11y_health.core.exceptions import ConcurrentRollupError
from a11y_health.models.enums import ScoreSnapshotOwnerType
from a11y_health.services import owner as owner_service
from a11y_health.services.owner import ChildrenRead
from tests.factories import (
    SessionFactory,
    advisory_lock_waiters,
    latest_brand_snapshot,
    latest_ou_snapshot,
    make_app,
    make_brand,
    make_org_unit,
    make_score_snapshot,
    substitute_children_read,
)

pytestmark = pytest.mark.integration

_STALE_AT = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
_NEWER_AT = datetime(2026, 4, 1, 13, 0, 0, tzinfo=UTC)
_DEADLINE = 5.0


async def _race_stale_rollup_against_newer_observation(
    committed_session_factory: SessionFactory,
    mocker,
    *,
    app_id: int,
    owner_type: ScoreSnapshotOwnerType,
    run_rollup: Callable[[AsyncSession], Awaitable[None]],
) -> None:
    """The #101 interleaving: session A's rollup pauses between its children
    read and its writes; session B commits a newer observation for `app_id`
    and a full rollup; A then resumes and both commit."""
    session_a = committed_session_factory()
    session_b = committed_session_factory()
    poll = committed_session_factory()

    stale_view_read = asyncio.Event()
    resume_stale_rollup = asyncio.Event()

    # Freeze session A between its input read and its writes — the window the
    # interleaving needs. Session B runs the substituted read too, so only A
    # pauses.
    def pause_stale_session(read_children: ChildrenRead) -> ChildrenRead:
        async def pause_after_read(session: AsyncSession, owner_id: int) -> list:
            children = await read_children(session, owner_id)
            if session is session_a:
                stale_view_read.set()
                await resume_stale_rollup.wait()
            return children

        return pause_after_read

    substitute_children_read(mocker, owner_type, pause_stale_session)

    async def stale_rollup() -> None:
        await run_rollup(session_a)
        await session_a.commit()

    async def newer_observation_and_rollup() -> None:
        await make_score_snapshot(session_b, app_id=app_id, snapshot_at=_NEWER_AT, score=1.0)
        await session_b.commit()
        await run_rollup(session_b)
        await session_b.commit()

    # B either completes (unserialized) or blocks on A's owner lock
    # (serialized). Polling is forced here: Postgres emits no event for a
    # backend waiting on a lock.
    async def finished_or_blocked(task: asyncio.Task[None]) -> None:
        while not task.done() and await advisory_lock_waiters(poll) == 0:  # noqa: ASYNC110
            await asyncio.sleep(0.05)

    task_a = asyncio.create_task(stale_rollup())
    task_b: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(stale_view_read.wait(), timeout=_DEADLINE)

        task_b = asyncio.create_task(newer_observation_and_rollup())
        await asyncio.wait_for(finished_or_blocked(task_b), timeout=_DEADLINE)
        await poll.rollback()

        # With the lock in place B cannot finish while A holds its stale view;
        # B completing here means the rollup ran unserialized — fail loudly
        # now rather than only via the final-state assertion.
        assert not task_b.done(), "session B completed without blocking on the per-owner rollup lock"

        resume_stale_rollup.set()
        await asyncio.wait_for(task_a, timeout=_DEADLINE)
        await asyncio.wait_for(task_b, timeout=_DEADLINE)
    finally:
        # On a deadline miss, cancel before fixture teardown closes the
        # sessions out from under the tasks' in-flight statements.
        tasks = [task for task in (task_a, task_b) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def test_stale_org_unit_rollup_cannot_regress_a_newer_committed_observation(
    committed_session_factory: SessionFactory, mocker
) -> None:
    setup = committed_session_factory()
    org_unit_id = (await make_org_unit(setup)).id
    app_id = (await make_app(setup, name="Race App", slug="rollup-race-app", org_unit_id=org_unit_id)).id
    await make_score_snapshot(setup, app_id=app_id, snapshot_at=_STALE_AT, score=0.4)
    await setup.commit()

    await _race_stale_rollup_against_newer_observation(
        committed_session_factory,
        mocker,
        app_id=app_id,
        owner_type=ScoreSnapshotOwnerType.ORG_UNIT,
        run_rollup=lambda session: owner_service.rollup(session, ScoreSnapshotOwnerType.ORG_UNIT, org_unit_id),
    )

    # The newest observation survived the stale recompute's prune.
    latest = await latest_ou_snapshot(setup, org_unit_id)
    assert latest.snapshot_at == _NEWER_AT
    assert latest.score == approx(1.0)


async def test_stale_brand_rollup_cannot_regress_a_newer_committed_observation(
    committed_session_factory: SessionFactory, mocker
) -> None:
    setup = committed_session_factory()
    brand_id = (await make_brand(setup)).id
    org_unit_id = (await make_org_unit(setup)).id
    app = await make_app(
        setup, name="Brand Race App", slug="brand-race-app", org_unit_id=org_unit_id, brand_id=brand_id
    )
    await make_score_snapshot(setup, app_id=app.id, snapshot_at=_STALE_AT, score=0.4)
    await setup.commit()

    await _race_stale_rollup_against_newer_observation(
        committed_session_factory,
        mocker,
        app_id=app.id,
        owner_type=ScoreSnapshotOwnerType.BRAND,
        run_rollup=lambda session: owner_service.rollup(session, ScoreSnapshotOwnerType.BRAND, brand_id),
    )

    latest = await latest_brand_snapshot(setup, brand_id)
    assert latest.snapshot_at == _NEWER_AT
    assert latest.score == approx(1.0)


async def test_a_deadlock_loser_surfaces_as_the_retryable_concurrent_rollup_error(engine: AsyncEngine) -> None:
    # Plain sessions, not committed_session_factory: nothing writes a row —
    # advisory xact locks vanish with the sessions — so the factory's
    # all-tables TRUNCATE teardown would be pure waste.
    session_a = AsyncSession(bind=engine)
    session_b = AsyncSession(bind=engine)
    try:
        await owner_service._acquire_rollup_lock(session_a, ScoreSnapshotOwnerType.ORG_UNIT, 1)
        await owner_service._acquire_rollup_lock(session_b, ScoreSnapshotOwnerType.ORG_UNIT, 2)

        # Cross acquisitions form the ADR 0029 cycle: each session waits on the lock
        # the other holds, and Postgres fails exactly one transaction (40P01).
        results = await asyncio.wait_for(
            asyncio.gather(
                owner_service._acquire_rollup_lock(session_a, ScoreSnapshotOwnerType.ORG_UNIT, 2),
                owner_service._acquire_rollup_lock(session_b, ScoreSnapshotOwnerType.ORG_UNIT, 1),
                return_exceptions=True,
            ),
            timeout=_DEADLINE * 2,
        )
    finally:
        await session_a.close()
        await session_b.close()

    errors = [result for result in results if isinstance(result, BaseException)]
    assert len(errors) == 1, f"exactly one session must lose the deadlock, got {results!r}"
    assert isinstance(errors[0], ConcurrentRollupError)
    assert "retry the request" in str(errors[0])


async def test_rollups_for_different_owners_do_not_serialize_each_other(
    committed_session_factory: SessionFactory,
) -> None:
    setup = committed_session_factory()
    brand_id = (await make_brand(setup)).id
    org_unit_id = (await make_org_unit(setup)).id
    app = await make_app(
        setup, name="Granularity App", slug="granularity-app", org_unit_id=org_unit_id, brand_id=brand_id
    )
    await make_score_snapshot(setup, app_id=app.id, snapshot_at=_STALE_AT)
    await setup.commit()

    session_a = committed_session_factory()
    session_b = committed_session_factory()

    # Hold an org-unit lock whose numeric id equals the brand's: a brand
    # rollup must not wait on it — the owner kind is part of the lock key,
    # and locks are per owner, never global.
    await owner_service._acquire_rollup_lock(session_a, ScoreSnapshotOwnerType.ORG_UNIT, brand_id)

    async def brand_rollup() -> None:
        await owner_service.rollup(session_b, ScoreSnapshotOwnerType.BRAND, brand_id)
        await session_b.commit()

    await asyncio.wait_for(brand_rollup(), timeout=_DEADLINE)
    await session_a.rollback()

    assert (await latest_brand_snapshot(setup, brand_id)).snapshot_at == _STALE_AT
