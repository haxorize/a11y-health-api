from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import literal, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from a11y_health.core.exceptions import CircularReferenceError, NotFoundError
from a11y_health.models.org_unit import OrgUnit
from a11y_health.schemas.org_unit import OrgUnitCreate, OrgUnitUpdate
from a11y_health.services.score import rollup_org_unit_scores

_RESOURCE = "Org unit"


async def create_org_unit(session: AsyncSession, data: OrgUnitCreate) -> OrgUnit:
    if data.parent_id is not None:
        await get_org_unit(session, data.parent_id)
    org_unit = OrgUnit(**data.model_dump())
    session.add(org_unit)
    await session.flush()
    await session.refresh(org_unit)
    return org_unit


async def list_org_units(session: AsyncSession, *, offset: int = 0, limit: int = 20) -> Sequence[OrgUnit]:
    result = await session.execute(select(OrgUnit).order_by(OrgUnit.id).offset(offset).limit(limit))
    return result.scalars().all()


async def get_org_unit(session: AsyncSession, org_unit_id: int) -> OrgUnit:
    org_unit = await session.get(OrgUnit, org_unit_id)
    if org_unit is None:
        raise NotFoundError(_RESOURCE, org_unit_id)
    return org_unit


async def update_org_unit(session: AsyncSession, org_unit_id: int, data: OrgUnitUpdate) -> OrgUnit:
    org_unit = await get_org_unit(session, org_unit_id)
    updates = data.model_dump(exclude_unset=True)
    old_parent_id = org_unit.parent_id
    if "parent_id" in updates:
        new_parent_id = updates["parent_id"]
        if new_parent_id is not None:
            await get_org_unit(session, new_parent_id)
            if new_parent_id == org_unit_id:
                raise CircularReferenceError(_RESOURCE, org_unit_id, new_parent_id)
            descendant_ids = {d.id for d in await get_descendants(session, org_unit_id)}
            if new_parent_id in descendant_ids:
                raise CircularReferenceError(_RESOURCE, org_unit_id, new_parent_id)
        reparented = new_parent_id != old_parent_id
    else:
        reparented = False
    for field, value in updates.items():
        setattr(org_unit, field, value)
    await session.flush()
    await session.refresh(org_unit)

    if reparented:
        now = datetime.now(UTC)
        if old_parent_id is not None:
            await rollup_org_unit_scores(session, old_parent_id, now)
        if org_unit.parent_id is not None:
            await rollup_org_unit_scores(session, org_unit.parent_id, now)

    return org_unit


async def get_ancestors(session: AsyncSession, org_unit_id: int) -> list[OrgUnit]:
    await get_org_unit(session, org_unit_id)
    depth = literal(0).label("depth")
    cte = select(OrgUnit, depth).where(OrgUnit.id == org_unit_id).cte(name="ancestors", recursive=True)
    parent = aliased(OrgUnit)
    cte = cte.union_all(select(parent, (cte.c.depth + 1).label("depth")).where(parent.id == cte.c.parent_id))
    result = await session.execute(
        select(OrgUnit).join(cte, OrgUnit.id == cte.c.id).where(OrgUnit.id != org_unit_id).order_by(cte.c.depth)
    )
    return list(result.scalars().all())


async def get_descendants(session: AsyncSession, org_unit_id: int) -> list[OrgUnit]:
    await get_org_unit(session, org_unit_id)
    cte = select(OrgUnit).where(OrgUnit.parent_id == org_unit_id).cte(name="descendants", recursive=True)
    child = aliased(OrgUnit)
    cte = cte.union_all(select(child).where(child.parent_id == cte.c.id))
    result = await session.execute(select(OrgUnit).join(cte, OrgUnit.id == cte.c.id))
    return list(result.scalars().all())


async def delete_org_unit(session: AsyncSession, org_unit_id: int) -> None:
    org_unit = await get_org_unit(session, org_unit_id)
    await session.delete(org_unit)
    await session.flush()
