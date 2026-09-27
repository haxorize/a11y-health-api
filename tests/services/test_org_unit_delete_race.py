"""Two-session coverage for writes naming an Org Unit deleted underneath
them (#178, ADR 0048).

Each case leaves an Org Unit's delete uncommitted, runs a write that names
that unit, and records whether the write was waiting when the delete
committed. The write's existence check still sees the unit, so what decides
the race is its foreign-key check, which waits on the delete's row lock. The
App deletion race instead pauses the App's delete before its rollup, so the
Org Unit's delete runs into it mid-operation. Real commits on separate
connections (`committed_session_factory`) put the two in separate
transactions that contend on real locks, each reading only what the other has
committed.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import HasDependentsError, NotFoundError
from a11y_health.models.app import App
from a11y_health.schemas.app import AppCreate, AppUpdate
from a11y_health.schemas.org_unit import OrgUnitCreate, OrgUnitUpdate
from a11y_health.services import app as app_service
from a11y_health.services import org_unit as org_unit_service
from a11y_health.services import scoring_orchestration
from tests.factories import (
    RACE_DEADLINE,
    SessionFactory,
    backend_pid,
    cancel_tasks,
    finished_or_blocked,
    make_app,
    make_brand,
    make_org_unit,
    make_score_snapshot,
    race_behind_open_transaction,
)

pytestmark = pytest.mark.integration


@dataclass(frozen=True)
class _Tree:
    deleted_id: int
    brand_id: int
    app_id: int
    other_unit_id: int


Write = Callable[[AsyncSession, _Tree], Awaitable[object]]


async def _create_app(session: AsyncSession, tree: _Tree) -> None:
    data = AppCreate(name="New App", brand_id=tree.brand_id, org_unit_id=tree.deleted_id)
    await app_service.create_app(session, data)


async def _move_app(session: AsyncSession, tree: _Tree) -> None:
    await app_service.update_app(session, tree.app_id, AppUpdate(org_unit_id=tree.deleted_id))


async def _create_child(session: AsyncSession, tree: _Tree) -> None:
    await org_unit_service.create_org_unit(session, OrgUnitCreate(name="Child", parent_id=tree.deleted_id))


async def _reparent_under(session: AsyncSession, tree: _Tree) -> None:
    await org_unit_service.update_org_unit(session, tree.other_unit_id, OrgUnitUpdate(parent_id=tree.deleted_id))


# Each case reds with an IntegrityError on its foreign key when its write site
# leaves that key unmapped.
@pytest.mark.parametrize(
    "write",
    [_create_app, _move_app, _create_child, _reparent_under],
    ids=["app-create", "app-move", "org-unit-create", "org-unit-reparent"],
)
async def test_a_write_naming_a_unit_deleted_underneath_it_is_not_found(
    committed_session_factory: SessionFactory, write: Write
) -> None:
    setup = committed_session_factory()
    root_id = (await make_org_unit(setup, name="Root")).id
    deleted_id = (await make_org_unit(setup, name="Deleted", parent_id=root_id)).id
    other_unit_id = (await make_org_unit(setup, name="Other", parent_id=root_id)).id
    brand_id = (await make_brand(setup)).id
    app_id = (await make_app(setup, brand_id=brand_id, org_unit_id=other_unit_id)).id
    await setup.commit()
    tree = _Tree(deleted_id=deleted_id, brand_id=brand_id, app_id=app_id, other_unit_id=other_unit_id)

    async def delete(session: AsyncSession) -> None:
        await org_unit_service.delete_org_unit(session, deleted_id)

    async def act(session: AsyncSession) -> None:
        await write(session, tree)

    waited, outcome = await race_behind_open_transaction(committed_session_factory, delete, act)

    assert waited
    assert isinstance(outcome, NotFoundError)
    assert str(outcome) == f"Org unit {deleted_id} not found"


# Reds with a 40P01 when the App's delete locks the App before its Org Unit:
# the unit's delete holds the unit and waits on the App in its dependents
# check, and the App's rollup then inserts the unit's snapshot, whose key
# check waits on the unit.
async def test_an_org_unit_deleted_mid_app_delete_waits_and_has_dependents(
    committed_session_factory: SessionFactory, mocker
) -> None:
    setup = committed_session_factory()
    unit_id = (await make_org_unit(setup, name="Unit")).id
    brand_id = (await make_brand(setup)).id
    deleted_app_id = (await make_app(setup, slug="deleted", brand_id=brand_id, org_unit_id=unit_id)).id
    # The unit keeps a scored App and has no snapshot of its own yet, so the
    # rollup inserts one, and the unit's delete has nothing to refuse on
    # before it reaches the deleted App.
    kept_app_id = (await make_app(setup, slug="kept", brand_id=brand_id, org_unit_id=unit_id)).id
    await make_score_snapshot(setup, app_id=kept_app_id)
    await setup.commit()
    app_deleting = committed_session_factory()
    unit_deleting = committed_session_factory()
    poll = committed_session_factory()

    app_flushed = asyncio.Event()
    resume = asyncio.Event()
    real_rollups = scoring_orchestration.on_app_latest_snapshot_changed

    async def pause_before_rollups(session: AsyncSession, app: App) -> None:
        app_flushed.set()
        await resume.wait()
        await real_rollups(session, app)

    mocker.patch.object(scoring_orchestration, "on_app_latest_snapshot_changed", pause_before_rollups)

    async def delete_app() -> None:
        await app_service.delete_app(app_deleting, deleted_app_id)
        await app_deleting.commit()

    async def delete_unit() -> HasDependentsError | None:
        try:
            await org_unit_service.delete_org_unit(unit_deleting, unit_id)
            await unit_deleting.commit()
        except HasDependentsError as error:
            await unit_deleting.rollback()
            return error
        return None

    app_deletion = asyncio.create_task(delete_app())
    unit_deletion: asyncio.Task[HasDependentsError | None] | None = None
    try:
        await asyncio.wait_for(app_flushed.wait(), timeout=RACE_DEADLINE)
        unit_deleting_pid = await backend_pid(unit_deleting)
        unit_deletion = asyncio.create_task(delete_unit())
        assert await finished_or_blocked(poll, unit_deletion, unit_deleting_pid)
        resume.set()
        await asyncio.wait_for(app_deletion, timeout=RACE_DEADLINE)
        outcome = await asyncio.wait_for(unit_deletion, timeout=RACE_DEADLINE)
    finally:
        await cancel_tasks(app_deletion, unit_deletion)

    assert isinstance(outcome, HasDependentsError)
    assert await setup.get(App, deleted_app_id) is None


# Reds with a NotFoundError for an App that exists when the App's delete takes
# a miss on its Org Unit lock as the App being gone: the unit it waited on was
# deleted once the App moved out of it.
async def test_an_app_moved_out_of_a_unit_deleted_underneath_its_delete_is_deleted(
    committed_session_factory: SessionFactory,
) -> None:
    setup = committed_session_factory()
    root_id = (await make_org_unit(setup, name="Root")).id
    deleted_id = (await make_org_unit(setup, name="Deleted", parent_id=root_id)).id
    other_unit_id = (await make_org_unit(setup, name="Other", parent_id=root_id)).id
    app_id = (await make_app(setup, org_unit_id=deleted_id)).id
    await setup.commit()

    async def move_app_then_delete_unit(session: AsyncSession) -> None:
        await app_service.update_app(session, app_id, AppUpdate(org_unit_id=other_unit_id))
        await org_unit_service.delete_org_unit(session, deleted_id)

    async def delete_app(session: AsyncSession) -> None:
        await app_service.delete_app(session, app_id)

    waited, outcome = await race_behind_open_transaction(
        committed_session_factory, move_app_then_delete_unit, delete_app
    )

    assert waited
    assert outcome is None
    assert await setup.get(App, app_id) is None
