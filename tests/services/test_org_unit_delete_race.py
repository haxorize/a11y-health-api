"""Two-session coverage for writes naming an Org Unit deleted underneath
them (#178, ADR 0048).

Each case leaves an Org Unit's delete uncommitted, runs a write that names
that unit, and records whether the write was waiting when the delete
committed. The write's existence check still sees the unit, so what decides
the race is its foreign-key check, which waits on the delete's row lock.
Real commits on separate connections (`committed_session_factory`) are what
let the two sessions see each other.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import NotFoundError
from a11y_health.schemas.app import AppCreate, AppUpdate
from a11y_health.schemas.org_unit import OrgUnitCreate, OrgUnitUpdate
from a11y_health.services import app as app_service
from a11y_health.services import org_unit as org_unit_service
from tests.factories import SessionFactory, make_app, make_brand, make_org_unit, race_behind_open_transaction

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
    assert outcome.resource_id == deleted_id
