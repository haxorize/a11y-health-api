"""Two-session coverage for App and Org Unit updates racing a write to the same
row (ADR 0048).

Each case leaves the first write uncommitted and runs the update against the
same row in a second session. Real commits on separate connections
(`committed_session_factory`) put the two in separate transactions that
contend on real locks, each reading only what the other has committed.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import pytest
from pytest import approx
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import NotFoundError
from a11y_health.schemas.app import AppUpdate
from a11y_health.schemas.org_unit import OrgUnitUpdate
from a11y_health.services import app as app_service
from a11y_health.services import org_unit as org_unit_service
from tests.factories import (
    SessionFactory,
    latest_ou_snapshot,
    make_app,
    make_org_unit,
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
# before the first move, not the one the first move put it in.
async def test_a_move_behind_another_move_rolls_up_the_unit_the_app_left(
    committed_session_factory: SessionFactory,
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

    async def move_to_middle(session: AsyncSession) -> None:
        await app_service.update_app(session, moved_id, AppUpdate(org_unit_id=middle_id))

    async def move_to_last(session: AsyncSession) -> None:
        await app_service.update_app(session, moved_id, AppUpdate(org_unit_id=last_id))

    waited, outcome = await race_behind_open_transaction(committed_session_factory, move_to_middle, move_to_last)

    assert waited
    assert outcome is None
    read = committed_session_factory()
    assert (await latest_ou_snapshot(read, middle_id)).score == approx(1.0)
    assert (await latest_ou_snapshot(read, last_id)).score == approx(0.6)
