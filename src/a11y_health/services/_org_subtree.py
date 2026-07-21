"""Org-unit subtree expansion shared across resource and scoring services.

A shared underscore helper (like `_latest_snapshot`) so consumers on both
sides of the two-tier call rule — `app`'s descendant-expanding filter,
`score`'s `under_org_unit_id` scope, and `org_unit`'s reparent-cycle check —
get the one recursive-CTE definition without importing a sibling resource
service.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from a11y_health.models.org_unit import OrgUnit


async def get_descendant_ids(session: AsyncSession, org_unit_ids: list[int]) -> set[int]:
    if not org_unit_ids:
        return set()
    cte = select(OrgUnit.id).where(OrgUnit.id.in_(org_unit_ids)).cte(name="subtree", recursive=True)
    child = aliased(OrgUnit)
    cte = cte.union_all(select(child.id).where(child.parent_id == cte.c.id))
    result = await session.execute(select(cte.c.id))
    return {row[0] for row in result}
