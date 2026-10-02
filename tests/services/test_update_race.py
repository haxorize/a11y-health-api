"""Two-session coverage for App and Org Unit updates racing a write to the same
row (ADR 0048).

Each case leaves the first write uncommitted and runs the update against the
same row in a second session. Real commits on separate connections
(`committed_session_factory`) put the two in separate transactions that
contend on real locks, each reading only what the other has committed.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from pytest import approx
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import NotFoundError
from a11y_health.models.app import App
from a11y_health.schemas.app import AppUpdate
from a11y_health.schemas.org_unit import OrgUnitUpdate
from a11y_health.services import app as app_service
from a11y_health.services import org_unit as org_unit_service
from a11y_health.services import scan_run as scan_run_service
from tests.factories import (
    SessionFactory,
    latest_ou_snapshot,
    make_app,
    make_org_unit,
    make_scan_run,
    make_score_snapshot,
    race_behind_open_transaction,
)

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class _Tree:
    app_id: int
    unit_id: int
    other_unit_id: int


Write = Callable[[AsyncSession, _Tree], Awaitable[object]]


async def _delete_app(session: AsyncSession, tree: _Tree) -> None:
    await app_service.delete_app(session, tree.app_id)


async def _delete_unit(session: AsyncSession, tree: _Tree) -> None:
    await org_unit_service.delete_org_unit(session, tree.unit_id)


async def _move_app(session: AsyncSession, tree: _Tree) -> None:
    await app_service.update_app(session, tree.app_id, AppUpdate(org_unit_id=tree.other_unit_id))


async def _rename_unit(session: AsyncSession, tree: _Tree) -> None:
    await org_unit_service.update_org_unit(session, tree.unit_id, OrgUnitUpdate(name="Renamed"))


async def _reparent_unit(session: AsyncSession, tree: _Tree) -> None:
    await org_unit_service.update_org_unit(session, tree.unit_id, OrgUnitUpdate(parent_id=tree.other_unit_id))


# Each case reds with a StaleDataError when its update loads the row without
# locking it: the UPDATE waits on the delete, then matches no row.
@pytest.mark.parametrize(
    ("delete", "update", "not_found"),
    [
        (_delete_app, _move_app, "App {app_id} not found"),
        (_delete_unit, _rename_unit, "Org unit {unit_id} not found"),
        (_delete_unit, _reparent_unit, "Org unit {unit_id} not found"),
    ],
    ids=["app-move", "org-unit-rename", "org-unit-reparent"],
)
async def test_an_update_of_a_row_deleted_underneath_it_is_not_found(
    committed_session_factory: SessionFactory, delete: Write, update: Write, not_found: str
) -> None:
    setup = committed_session_factory()
    root_id = (await make_org_unit(setup, name="Root")).id
    # The App lives outside the deleted unit, so the unit has no dependents.
    unit_id = (await make_org_unit(setup, name="Unit", parent_id=root_id)).id
    other_unit_id = (await make_org_unit(setup, name="Other", parent_id=root_id)).id
    app_id = (await make_app(setup, org_unit_id=root_id)).id
    await setup.commit()
    tree = _Tree(app_id=app_id, unit_id=unit_id, other_unit_id=other_unit_id)

    async def hold(session: AsyncSession) -> None:
        await delete(session, tree)

    async def act(session: AsyncSession) -> None:
        await update(session, tree)

    waited, outcome = await race_behind_open_transaction(committed_session_factory, hold, act)

    assert waited
    assert isinstance(outcome, NotFoundError)
    assert str(outcome) == not_found.format(app_id=app_id, unit_id=unit_id)


# Reds with the unit the App left keeping its stale score when the second move
# reads the App's owner before waiting: it rolls up the unit the App was in
# before the first move, not the one the first move put it in. The preloaded
# case reds when the locked load drops populate_existing, since the App this
# session read before the wait keeps that unit.
@pytest.mark.parametrize("preload", [False, True], ids=["cold", "preloaded"])
async def test_a_move_behind_another_move_rolls_up_the_unit_the_app_left(
    committed_session_factory: SessionFactory, preload: bool
) -> None:
    setup = committed_session_factory()
    root_id = (await make_org_unit(setup, name="Root")).id
    first_id = (await make_org_unit(setup, name="First", parent_id=root_id)).id
    middle_id = (await make_org_unit(setup, name="Middle", parent_id=root_id)).id
    last_id = (await make_org_unit(setup, name="Last", parent_id=root_id)).id
    moved_id = (await make_app(setup, slug="moved", org_unit_id=first_id)).id
    await make_score_snapshot(setup, app_id=moved_id, score=0.6)
    kept_id = (await make_app(setup, slug="kept", org_unit_id=middle_id)).id
    await make_score_snapshot(setup, app_id=kept_id, score=1.0)
    await setup.commit()
    loaded: list[App | None] = []

    async def move_to_middle(session: AsyncSession) -> None:
        await app_service.update_app(session, moved_id, AppUpdate(org_unit_id=middle_id))

    async def move_to_last(session: AsyncSession) -> None:
        if preload:
            # Held, as a caller that read the App earlier in its transaction
            # holds it; the identity map drops an instance nobody references.
            loaded.append(await session.get(App, moved_id))
        await app_service.update_app(session, moved_id, AppUpdate(org_unit_id=last_id))

    waited, outcome = await race_behind_open_transaction(committed_session_factory, move_to_middle, move_to_last)

    assert waited
    assert outcome is None
    read = committed_session_factory()
    assert (await latest_ou_snapshot(read, middle_id)).score == approx(1.0)
    assert (await latest_ou_snapshot(read, last_id)).score == approx(0.6)


@dataclass(frozen=True)
class _Move:
    moved_id: int
    left_id: int
    joined_id: int


async def _app_in_one_unit_of_two(session_factory: SessionFactory) -> tuple[AsyncSession, _Move]:
    # The joined unit holds a second App scored 0.6, so its rollup shows
    # whether it still counts the moved App's latest score.
    setup = session_factory()
    root_id = (await make_org_unit(setup, name="Root")).id
    left_id = (await make_org_unit(setup, name="Left", parent_id=root_id)).id
    joined_id = (await make_org_unit(setup, name="Joined", parent_id=root_id)).id
    moved_id = (await make_app(setup, slug="moved", org_unit_id=left_id)).id
    kept_id = (await make_app(setup, slug="kept", org_unit_id=joined_id)).id
    await make_score_snapshot(setup, app_id=kept_id, score=0.6)
    return setup, _Move(moved_id=moved_id, left_id=left_id, joined_id=joined_id)


# Reds with the joined unit still counting the deleted App when the delete
# locks only the unit: the move commits under it, and the delete rolls up the
# unit the App left. The preloaded case reds when the App's locked load drops
# populate_existing, since the App this session read keeps the unit it left.
@pytest.mark.parametrize("preload", [False, True], ids=["cold", "preloaded"])
async def test_an_app_deleted_behind_its_move_rolls_up_the_unit_it_joined(
    committed_session_factory: SessionFactory, preload: bool
) -> None:
    setup, move = await _app_in_one_unit_of_two(committed_session_factory)
    await make_score_snapshot(setup, app_id=move.moved_id, score=1.0)
    await setup.commit()
    loaded: list[App | None] = []

    async def move_app(session: AsyncSession) -> None:
        await app_service.update_app(session, move.moved_id, AppUpdate(org_unit_id=move.joined_id))

    async def delete_app(session: AsyncSession) -> None:
        if preload:
            # Held, as a caller that read the App earlier in its transaction
            # holds it; the identity map drops an instance nobody references.
            loaded.append(await session.get(App, move.moved_id))
        await app_service.delete_app(session, move.moved_id)

    waited, outcome = await race_behind_open_transaction(committed_session_factory, move_app, delete_app)

    assert waited
    assert outcome is None
    assert (await latest_ou_snapshot(committed_session_factory(), move.joined_id)).score == approx(0.6)


# Reds with the joined unit still counting the deleted run's score when the
# delete reads the App without locking it: it rolls up the unit the App left.
async def test_a_scan_run_deleted_behind_its_apps_move_rolls_up_the_unit_it_joined(
    committed_session_factory: SessionFactory,
) -> None:
    setup, move = await _app_in_one_unit_of_two(committed_session_factory)
    older = await make_scan_run(setup, app_id=move.moved_id, scanned_at=datetime(2026, 3, 1, tzinfo=UTC))
    await make_score_snapshot(
        setup, app_id=move.moved_id, scan_run_id=older.id, score=0.4, snapshot_at=datetime(2026, 3, 1, tzinfo=UTC)
    )
    newer = await make_scan_run(setup, app_id=move.moved_id, scanned_at=datetime(2026, 4, 1, tzinfo=UTC))
    await make_score_snapshot(
        setup, app_id=move.moved_id, scan_run_id=newer.id, score=1.0, snapshot_at=datetime(2026, 4, 1, tzinfo=UTC)
    )
    newer_id = newer.id
    await setup.commit()

    async def move_app(session: AsyncSession) -> None:
        await app_service.update_app(session, move.moved_id, AppUpdate(org_unit_id=move.joined_id))

    async def delete_newer_run(session: AsyncSession) -> None:
        await scan_run_service.delete_scan_run(session, newer_id)

    waited, outcome = await race_behind_open_transaction(committed_session_factory, move_app, delete_newer_run)

    assert waited
    assert outcome is None
    # (0.4 + 0.6) / 2: the moved App falls back to its older run.
    assert (await latest_ou_snapshot(committed_session_factory(), move.joined_id)).score == approx(0.5)


# Reds at `waited` when App deletion locks its unit more strongly than KEY
# SHARE: an update of the unit then waits out every App deletion in it.
async def test_an_org_unit_update_does_not_wait_on_an_app_deletion_in_it(
    committed_session_factory: SessionFactory,
) -> None:
    setup, move = await _app_in_one_unit_of_two(committed_session_factory)
    await setup.commit()

    async def delete_app(session: AsyncSession) -> None:
        await app_service.delete_app(session, move.moved_id)

    async def rename_unit(session: AsyncSession) -> None:
        await org_unit_service.update_org_unit(session, move.left_id, OrgUnitUpdate(name="Renamed"))

    waited, outcome = await race_behind_open_transaction(committed_session_factory, delete_app, rename_unit)

    assert not waited
    assert outcome is None


# Reds with a second 204 when App deletion locks only the unit: the second
# delete matches no row and returns as if it had deleted the App.
async def test_an_app_deleted_behind_its_own_deletion_is_not_found(
    committed_session_factory: SessionFactory,
) -> None:
    setup, move = await _app_in_one_unit_of_two(committed_session_factory)
    await setup.commit()

    async def delete_app(session: AsyncSession) -> None:
        await app_service.delete_app(session, move.moved_id)

    waited, outcome = await race_behind_open_transaction(committed_session_factory, delete_app, delete_app)

    assert waited
    assert isinstance(outcome, NotFoundError)
    assert str(outcome) == f"App {move.moved_id} not found"
