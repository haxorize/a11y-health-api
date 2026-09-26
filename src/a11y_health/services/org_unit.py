from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager

from sqlalchemy import literal, literal_column, not_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from a11y_health.core import existence, integrity
from a11y_health.core.exceptions import CircularReferenceError, DuplicateRootError, HasDependentsError
from a11y_health.models.app import FK_APP_ORG_UNIT_ID
from a11y_health.models.org_unit import FK_ORG_UNIT_PARENT_ID, UQ_ORG_UNIT_SINGLE_ROOT, OrgUnit
from a11y_health.models.score_snapshot import FK_SCORE_SNAPSHOT_ORG_UNIT_ID
from a11y_health.schemas.org_unit import OrgUnitCreate, OrgUnitUpdate
from a11y_health.services import scoring_orchestration
from a11y_health.services._org_subtree import get_descendant_ids


async def get_root_id(session: AsyncSession, *, exclude_id: int | None = None) -> int | None:
    stmt = select(OrgUnit.id).where(OrgUnit.parent_id.is_(None))
    if exclude_id is not None:
        stmt = stmt.where(OrgUnit.id != exclude_id)
    return (await session.execute(stmt.limit(1))).scalar_one_or_none()


async def _check_no_other_root(session: AsyncSession, exclude_id: int | None = None) -> None:
    existing_root_id = await get_root_id(session, exclude_id=exclude_id)
    if existing_root_id is not None:
        raise DuplicateRootError(OrgUnit, existing_root_id)


def _root_race_guard(session: AsyncSession) -> AbstractAsyncContextManager[None]:
    """The single-root violation is only reachable when a concurrent transaction
    won the root race after `_check_no_other_root` passed."""
    return integrity.guard(session, {UQ_ORG_UNIT_SINGLE_ROOT: DuplicateRootError(OrgUnit)})


async def create_org_unit(session: AsyncSession, data: OrgUnitCreate) -> OrgUnit:
    if data.parent_id is not None:
        await get_org_unit(session, data.parent_id)
    else:
        await _check_no_other_root(session)
    org_unit = OrgUnit(**data.model_dump())
    async with _root_race_guard(session):
        session.add(org_unit)
    await session.refresh(org_unit)
    return org_unit


async def list_org_units(session: AsyncSession, *, parent_id: list[int] | None = None) -> Sequence[OrgUnit]:
    stmt = select(OrgUnit).order_by(OrgUnit.id)
    if parent_id:
        stmt = stmt.where(OrgUnit.parent_id.in_(parent_id))
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_org_unit(session: AsyncSession, org_unit_id: int) -> OrgUnit:
    return await existence.get_by_pk(session, OrgUnit, org_unit_id)


async def update_org_unit(session: AsyncSession, org_unit_id: int, data: OrgUnitUpdate) -> OrgUnit:
    org_unit = await get_org_unit(session, org_unit_id)
    old_parent_id = org_unit.parent_id
    updates = data.model_dump(exclude_unset=True)
    if "parent_id" in updates:
        new_parent_id = updates["parent_id"]
        if new_parent_id is not None:
            await get_org_unit(session, new_parent_id)
            # The subtree is inclusive of the unit itself, so self-parenting
            # and descendant-parenting fail as one membership check.
            if new_parent_id in await get_descendant_ids(session, [org_unit_id]):
                raise CircularReferenceError(OrgUnit, org_unit_id, new_parent_id)
        else:
            await _check_no_other_root(session, exclude_id=org_unit_id)
    async with _root_race_guard(session):
        for field, value in updates.items():
            setattr(org_unit, field, value)
    await session.refresh(org_unit)
    if "parent_id" in updates and org_unit.parent_id != old_parent_id:
        await scoring_orchestration.on_org_unit_reparented(
            session, old_parent_id=old_parent_id, new_parent_id=org_unit.parent_id
        )
    return org_unit


# Ancestors come back nearest parent first and the Root Org Unit (DOMAIN.md)
# last, with the unit itself excluded. The order is the route's contract, not
# an accident of the query.
async def get_ancestors(session: AsyncSession, org_unit_id: int) -> list[OrgUnit]:
    await get_org_unit(session, org_unit_id)
    depth = literal(0).label("depth")
    cte = select(OrgUnit, depth).where(OrgUnit.id == org_unit_id).cte(name="ancestors", recursive=True)
    parent = aliased(OrgUnit)
    cte = cte.union_all(select(parent, (cte.c.depth + 1).label("depth")).where(parent.id == cte.c.parent_id))
    # The depth differs every iteration, so a `union` would never see a repeat
    # row on a committed cycle. CYCLE stops the walk at the first repeated id
    # and flags that closing row, which is dropped below. CYCLE needs
    # PostgreSQL 14 or later. The flag is read unqualified: only the CTE
    # carries it, so the read survives the CTE being aliased.
    cte = cte.suffix_with("CYCLE id SET is_cycle USING path")
    result = await session.execute(
        select(OrgUnit)
        .join(cte, OrgUnit.id == cte.c.id)
        .where(OrgUnit.id != org_unit_id, not_(literal_column("is_cycle")))
        .order_by(cte.c.depth)
    )
    return list(result.scalars().all())


# The Dependents Guard (DOMAIN.md): an Org Unit with child Org Units, Apps, or
# Score Snapshots refuses deletion. The RESTRICT foreign keys decide it, and
# `integrity.guard` turns the violation into `HasDependentsError`.
async def delete_org_unit(session: AsyncSession, org_unit_id: int) -> None:
    org_unit = await get_org_unit(session, org_unit_id)
    # One instance for all three dependent FKs: guard raises at most once per
    # call.
    dependents = HasDependentsError(OrgUnit, org_unit_id)
    async with integrity.guard(
        session,
        {
            FK_ORG_UNIT_PARENT_ID: dependents,
            FK_APP_ORG_UNIT_ID: dependents,
            FK_SCORE_SNAPSHOT_ORG_UNIT_ID: dependents,
        },
    ):
        await session.delete(org_unit)
