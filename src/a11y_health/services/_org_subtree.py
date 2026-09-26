"""Org-unit subtree expansion shared across resource and scoring services.

A shared underscore helper (like `_latest_snapshot`) so consumers on both
sides of the two-tier call rule — `app`'s org-unit filter (subtree-expanding
by default, exact under `direct_only`), the Owner Dispatcher's
`under_org_unit_id` scope (`owner.py`), and `org_unit`'s reparent-cycle
check — get one recursive-CTE definition without importing a sibling
resource service. Two exports over that one CTE: `select_descendant_ids` to
embed the subtree inside a statement, `get_descendant_ids` when the caller
needs the ids as a Python set.

That consumer list is this module's own record. `services/` is one flat
package, so the underscore stops nothing here and no test names these
importers; `TestScoringModuleImports` covers `owner` alone.
"""

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from a11y_health.models.org_unit import OrgUnit


def select_descendant_ids(org_unit_ids: list[int]) -> Select[tuple[int]]:
    """The inclusive subtree as a SELECT, for embedding as an IN subquery in
    the caller's own statement instead of round-tripping the ids.

    `org_unit_ids` must be non-empty: an empty list renders an empty IN, which
    every caller guards before reaching here. The CTE is left unnamed so two
    subtrees can sit in one statement — a fixed name collides at compile time.
    `union` rather than `union_all`: the rows are bare ids, so on a committed
    cycle the walk comes back to an id already emitted and stops there.
    """
    cte = select(OrgUnit.id).where(OrgUnit.id.in_(org_unit_ids)).cte(recursive=True)
    child = aliased(OrgUnit)
    cte = cte.union(select(child.id).where(child.parent_id == cte.c.id))
    return select(cte.c.id)


async def get_descendant_ids(session: AsyncSession, org_unit_ids: list[int]) -> set[int]:
    if not org_unit_ids:
        return set()
    result = await session.execute(select_descendant_ids(org_unit_ids))
    return {row[0] for row in result}
