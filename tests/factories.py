from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.org_unit import OrgUnit


async def make_org_unit(db: AsyncSession, *, name: str = "Test Org", parent_id: int | None = None) -> OrgUnit:
    org_unit = OrgUnit(name=name, parent_id=parent_id)
    db.add(org_unit)
    await db.flush()
    return org_unit
