from collections import deque
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import CircularReferenceError, NotFoundError
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


async def get_org_unit(session: AsyncSession, org_unit_id: int) -> OrgUnit:
    org_unit = await session.get(OrgUnit, org_unit_id)
    if org_unit is None:
        raise NotFoundError("Org unit", org_unit_id)
    return org_unit


async def update_org_unit(session: AsyncSession, org_unit_id: int, data: OrgUnitUpdate) -> OrgUnit:
    org_unit = await get_org_unit(session, org_unit_id)
    updates = data.model_dump(exclude_unset=True)
    if "parent_id" in updates and updates["parent_id"] is not None:
        new_parent_id = updates["parent_id"]
        parent = await session.get(OrgUnit, new_parent_id)
        if parent is None:
            raise NotFoundError("Org unit", new_parent_id)
        if new_parent_id == org_unit_id:
            raise CircularReferenceError("Org unit", org_unit_id, new_parent_id)
        descendant_ids = {d.id for d in await get_descendants(session, org_unit_id)}
        if new_parent_id in descendant_ids:
            raise CircularReferenceError("Org unit", org_unit_id, new_parent_id)
    for field, value in updates.items():
        setattr(org_unit, field, value)
    await session.flush()
    await session.refresh(org_unit)
    return org_unit


async def get_ancestors(session: AsyncSession, org_unit_id: int) -> list[OrgUnit]:
    org_unit = await get_org_unit(session, org_unit_id)
    ancestors: list[OrgUnit] = []
    current = org_unit
    while current.parent_id is not None:
        parent = await session.get(OrgUnit, current.parent_id)
        if parent is None:
            raise NotFoundError("Org unit", current.parent_id)
        ancestors.append(parent)
        current = parent
    return ancestors


async def get_descendants(session: AsyncSession, org_unit_id: int) -> list[OrgUnit]:
    await get_org_unit(session, org_unit_id)
    descendants: list[OrgUnit] = []
    queue: deque[int] = deque([org_unit_id])
    while queue:
        parent_id = queue.popleft()
        result = await session.execute(select(OrgUnit).where(OrgUnit.parent_id == parent_id))
        children = result.scalars().all()
        for child in children:
            descendants.append(child)
            queue.append(child.id)
    return descendants


async def delete_org_unit(session: AsyncSession, org_unit_id: int) -> None:
    org_unit = await get_org_unit(session, org_unit_id)
    await session.delete(org_unit)
    await session.flush()
