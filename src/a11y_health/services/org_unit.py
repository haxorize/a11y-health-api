import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import NotFoundError
from a11y_health.models.org_unit import OrgUnit
from a11y_health.schemas.org_unit import OrgUnitCreate, OrgUnitUpdate


async def create_org_unit(session: AsyncSession, data: OrgUnitCreate) -> OrgUnit:
    if data.parent_id is not None:
        parent = await session.get(OrgUnit, data.parent_id)
        if parent is None:
            raise NotFoundError("Org unit", data.parent_id)
    org_unit = OrgUnit(**data.model_dump())
    session.add(org_unit)
    await session.flush()
    await session.refresh(org_unit)
    return org_unit


async def list_org_units(session: AsyncSession, *, offset: int = 0, limit: int = 20) -> Sequence[OrgUnit]:
    result = await session.execute(select(OrgUnit).offset(offset).limit(limit))
    return result.scalars().all()


async def get_org_unit(session: AsyncSession, org_unit_id: uuid.UUID) -> OrgUnit:
    org_unit = await session.get(OrgUnit, org_unit_id)
    if org_unit is None:
        raise NotFoundError("Org unit", org_unit_id)
    return org_unit


async def update_org_unit(session: AsyncSession, org_unit_id: uuid.UUID, data: OrgUnitUpdate) -> OrgUnit:
    org_unit = await get_org_unit(session, org_unit_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(org_unit, field, value)
    await session.flush()
    await session.refresh(org_unit)
    return org_unit


async def delete_org_unit(session: AsyncSession, org_unit_id: uuid.UUID) -> None:
    org_unit = await get_org_unit(session, org_unit_id)
    await session.delete(org_unit)
    await session.flush()
