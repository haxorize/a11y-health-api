import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import NotFoundError
from a11y_health.schemas.org_unit import OrgUnitCreate, OrgUnitUpdate
from a11y_health.services import org_unit as org_unit_service
from tests.factories import make_org_unit


async def test_create_org_unit(db_session: AsyncSession) -> None:
    org_unit = await org_unit_service.create_org_unit(db_session, OrgUnitCreate(name="Humana"))
    assert org_unit.name == "Humana"
    assert org_unit.parent_id is None
    assert org_unit.id is not None


async def test_create_org_unit_with_parent(db_session: AsyncSession) -> None:
    parent = await make_org_unit(db_session, name="Humana")
    child = await org_unit_service.create_org_unit(db_session, OrgUnitCreate(name="CenterWell", parent_id=parent.id))
    assert child.parent_id == parent.id


async def test_create_org_unit_with_invalid_parent(db_session: AsyncSession) -> None:
    fake_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
    with pytest.raises(NotFoundError, match="Org unit"):
        await org_unit_service.create_org_unit(db_session, OrgUnitCreate(name="Orphan", parent_id=fake_id))


async def test_list_org_units(db_session: AsyncSession) -> None:
    await make_org_unit(db_session, name="Humana")
    await make_org_unit(db_session, name="CenterWell")
    result = await org_unit_service.list_org_units(db_session)
    assert len(result) == 2


async def test_list_org_units_pagination(db_session: AsyncSession) -> None:
    for i in range(5):
        await make_org_unit(db_session, name=f"Org {i}")
    result = await org_unit_service.list_org_units(db_session, offset=1, limit=2)
    assert len(result) == 2


async def test_get_org_unit(db_session: AsyncSession) -> None:
    created = await make_org_unit(db_session, name="Humana")
    fetched = await org_unit_service.get_org_unit(db_session, created.id)
    assert fetched.id == created.id
    assert fetched.name == "Humana"


async def test_get_org_unit_not_found(db_session: AsyncSession) -> None:
    fake_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
    with pytest.raises(NotFoundError, match="Org unit"):
        await org_unit_service.get_org_unit(db_session, fake_id)


async def test_update_org_unit(db_session: AsyncSession) -> None:
    created = await make_org_unit(db_session, name="Humana")
    updated = await org_unit_service.update_org_unit(db_session, created.id, OrgUnitUpdate(name="Humana Inc."))
    assert updated.name == "Humana Inc."
    assert updated.id == created.id


async def test_update_org_unit_with_invalid_parent(db_session: AsyncSession) -> None:
    created = await make_org_unit(db_session, name="Humana")
    fake_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
    with pytest.raises(NotFoundError, match="Org unit"):
        await org_unit_service.update_org_unit(db_session, created.id, OrgUnitUpdate(parent_id=fake_id))


async def test_update_org_unit_not_found(db_session: AsyncSession) -> None:
    fake_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
    with pytest.raises(NotFoundError, match="Org unit"):
        await org_unit_service.update_org_unit(db_session, fake_id, OrgUnitUpdate(name="Ghost"))


async def test_delete_org_unit(db_session: AsyncSession) -> None:
    created = await make_org_unit(db_session, name="Humana")
    await org_unit_service.delete_org_unit(db_session, created.id)
    with pytest.raises(NotFoundError):
        await org_unit_service.get_org_unit(db_session, created.id)


async def test_delete_org_unit_not_found(db_session: AsyncSession) -> None:
    fake_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
    with pytest.raises(NotFoundError, match="Org unit"):
        await org_unit_service.delete_org_unit(db_session, fake_id)
