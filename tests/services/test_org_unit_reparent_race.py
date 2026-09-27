"""Two-session coverage for Org Unit reparent serialization (#176, ADR 0047).

Each race freezes session A's reparent right after its ancestry check, runs
session B's reparent to completion or to a lock wait, then releases A. Real
commits on separate connections (`committed_session_factory`) put the two in
separate transactions that contend on real locks, each reading only what the
other has committed.
"""

import asyncio
from datetime import UTC, datetime

import pytest
from pytest import approx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import CircularReferenceError, DuplicateRootError
from a11y_health.models.enums import ScoreSnapshotOwnerType
from a11y_health.models.org_unit import OrgUnit
from a11y_health.schemas.org_unit import OrgUnitUpdate
from a11y_health.services import org_unit as org_unit_service
from a11y_health.services import owner as owner_service
from tests.factories import (
    RACE_DEADLINE,
    SessionFactory,
    backend_pid,
    cancel_tasks,
    finished_or_blocked,
    latest_ou_snapshot,
    make_app,
    make_org_unit,
    make_score_snapshot,
    race_behind_open_transaction,
)

pytestmark = pytest.mark.integration

_OLDER_AT = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
# P2's own app observes last, so P2's recompute after the moved unit leaves
# lands on the same observation time and replaces the snapshot A wrote.
_NEWER_AT = datetime(2026, 4, 1, 13, 0, 0, tzinfo=UTC)


async def _race_reparents(
    committed_session_factory: SessionFactory,
    mocker,
    *,
    move_a: tuple[int, int],
    move_b: tuple[int, int],
    b_loads_first: bool = False,
) -> list[CircularReferenceError | None]:
    """Run A's reparent paused after its ancestry check, then B's, and return
    each one's outcome: `None` for a commit, or the `CircularReferenceError`
    it raised. Any other error propagates."""
    session_a = committed_session_factory()
    session_b = committed_session_factory()
    poll = committed_session_factory()

    a_checked = asyncio.Event()
    resume_a = asyncio.Event()
    real_get_descendant_ids = org_unit_service.get_descendant_ids

    async def pause_after_check(session: AsyncSession, org_unit_ids: list[int]) -> set[int]:
        descendant_ids = await real_get_descendant_ids(session, org_unit_ids)
        if session is session_a:
            a_checked.set()
            await resume_a.wait()
        return descendant_ids

    mocker.patch.object(org_unit_service, "get_descendant_ids", pause_after_check)

    # Held, because the identity map holds an unmodified instance weakly.
    loaded_by_b: list[OrgUnit | None] = []

    async def reparent(session: AsyncSession, move: tuple[int, int]) -> CircularReferenceError | None:
        org_unit_id, parent_id = move
        if session is session_b and b_loads_first:
            # Loaded before A commits, as a caller that read the unit earlier
            # in its transaction has.
            loaded_by_b.append(await session.get(OrgUnit, org_unit_id))
        try:
            await org_unit_service.update_org_unit(session, org_unit_id, OrgUnitUpdate(parent_id=parent_id))
            await session.commit()
        except CircularReferenceError as error:
            await session.rollback()
            return error
        return None

    task_a = asyncio.create_task(reparent(session_a, move_a))
    task_b: asyncio.Task[CircularReferenceError | None] | None = None
    try:
        await asyncio.wait_for(a_checked.wait(), timeout=RACE_DEADLINE)
        b_pid = await backend_pid(session_b)
        task_b = asyncio.create_task(reparent(session_b, move_b))
        await finished_or_blocked(poll, task_b, b_pid)
        resume_a.set()
        return [
            await asyncio.wait_for(task_a, timeout=RACE_DEADLINE),
            await asyncio.wait_for(task_b, timeout=RACE_DEADLINE),
        ]
    finally:
        await cancel_tasks(task_a, task_b)


async def _committed_parents(session: AsyncSession) -> dict[int, int | None]:
    await session.rollback()
    rows = await session.execute(select(OrgUnit.id, OrgUnit.parent_id))
    return dict(rows.tuples().all())


# Reds when update_org_unit takes no reparent lock: both moves commit.
async def test_crossing_reparents_cannot_both_commit_a_cycle(committed_session_factory: SessionFactory, mocker) -> None:
    setup = committed_session_factory()
    root_id = (await make_org_unit(setup, name="Root")).id
    x_id = (await make_org_unit(setup, name="X", parent_id=root_id)).id
    y_id = (await make_org_unit(setup, name="Y", parent_id=root_id)).id
    await setup.commit()

    outcomes = await _race_reparents(committed_session_factory, mocker, move_a=(x_id, y_id), move_b=(y_id, x_id))

    # A holds the tree lock through its check, so A wins and B, re-checking
    # against A's commit, is the one refused.
    assert outcomes[0] is None
    assert isinstance(outcomes[1], CircularReferenceError)
    assert await _committed_parents(setup) == {root_id: None, x_id: y_id, y_id: root_id}


# Reds when the reparent lock is taken after the unit is loaded, not before,
# and, where B loaded the unit first, when the load after the lock keeps the
# instance B read before A committed.
@pytest.mark.parametrize("b_loads_first", [False, True], ids=["fresh-session", "b-loaded-first"])
async def test_a_second_reparent_of_one_unit_rolls_up_the_parent_the_first_committed(
    committed_session_factory: SessionFactory, mocker, b_loads_first: bool
) -> None:
    setup = committed_session_factory()
    root_id = (await make_org_unit(setup, name="Root")).id
    p1_id = (await make_org_unit(setup, name="P1", parent_id=root_id)).id
    p2_id = (await make_org_unit(setup, name="P2", parent_id=root_id)).id
    p3_id = (await make_org_unit(setup, name="P3", parent_id=root_id)).id
    unit_id = (await make_org_unit(setup, name="Moved", parent_id=p1_id)).id
    moved_app = await make_app(setup, name="Moved App", slug="moved-app", org_unit_id=unit_id)
    await make_score_snapshot(setup, app_id=moved_app.id, snapshot_at=_OLDER_AT, score=1.0)
    p2_app = await make_app(setup, name="P2 App", slug="p2-app", org_unit_id=p2_id)
    await make_score_snapshot(setup, app_id=p2_app.id, snapshot_at=_NEWER_AT, score=0.2)
    await owner_service.rollup(setup, ScoreSnapshotOwnerType.ORG_UNIT, unit_id)
    await setup.commit()

    outcomes = await _race_reparents(
        committed_session_factory,
        mocker,
        move_a=(unit_id, p2_id),
        move_b=(unit_id, p3_id),
        b_loads_first=b_loads_first,
    )

    assert outcomes == [None, None]
    # B read P2 as the old parent, so P2 was re-rolled without the moved unit:
    # its own app alone. A stale read of P1 leaves P2 at (0.2 + 1.0) / 2 = 0.6.
    await setup.rollback()
    assert (await latest_ou_snapshot(setup, p2_id)).score == approx(0.2)


# Reds when a PATCH to a null parent skips the reparent lock: the promotion
# is refused at once, without waiting on the reparent in flight.
async def test_a_promotion_waits_on_a_reparent_in_flight(committed_session_factory: SessionFactory) -> None:
    setup = committed_session_factory()
    root_id = (await make_org_unit(setup, name="Root")).id
    x_id = (await make_org_unit(setup, name="X", parent_id=root_id)).id
    y_id = (await make_org_unit(setup, name="Y", parent_id=root_id)).id
    await setup.commit()

    async def move_x_under_y(session: AsyncSession) -> None:
        await org_unit_service.update_org_unit(session, x_id, OrgUnitUpdate(parent_id=y_id))

    async def promote_y(session: AsyncSession) -> None:
        await org_unit_service.update_org_unit(session, y_id, OrgUnitUpdate(parent_id=None))

    waited, outcome = await race_behind_open_transaction(committed_session_factory, move_x_under_y, promote_y)

    assert waited
    assert isinstance(outcome, DuplicateRootError)
