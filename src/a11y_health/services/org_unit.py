from collections.abc import Mapping, Sequence
from contextlib import AbstractAsyncContextManager

from sqlalchemy import func, literal, literal_column, not_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from a11y_health.core import existence, integrity
from a11y_health.core.exceptions import CircularReferenceError, DuplicateRootError, HasDependentsError, NotFoundError
from a11y_health.models.app import FK_APP_ORG_UNIT_ID
from a11y_health.models.org_unit import FK_ORG_UNIT_PARENT_ID, UQ_ORG_UNIT_SINGLE_ROOT, OrgUnit
from a11y_health.models.score_snapshot import FK_SCORE_SNAPSHOT_ORG_UNIT_ID
from a11y_health.schemas.org_unit import OrgUnitCreate, OrgUnitUpdate
from a11y_health.services import scoring_orchestration
from a11y_health.services._org_subtree import get_descendant_ids

_REPARENT_LOCK_KEY = "reparent:org_unit_tree"


async def get_root_org_unit_id(session: AsyncSession) -> int | None:
    """The Root Org Unit's id, or `None` before onboarding or once the Root Org
    Unit is deleted, never a failed lookup."""
    stmt = select(OrgUnit.id).where(OrgUnit.parent_id.is_(None))
    # Unordered is safe: ADR 0026's partial unique index allows one parentless
    # row at most.
    return (await session.execute(stmt.limit(1))).scalar_one_or_none()


async def _check_no_other_root(session: AsyncSession, promoted_id: int | None = None) -> None:
    # A unit promoted while already the Root Org Unit is not its own competitor.
    existing_root_id = await get_root_org_unit_id(session)
    if existing_root_id is not None and existing_root_id != promoted_id:
        raise DuplicateRootError(OrgUnit, existing_root_id)


def _write_race_guard(
    session: AsyncSession, parent_reference: Mapping[str, NotFoundError]
) -> AbstractAsyncContextManager[None]:
    """Both violations are only reachable through a concurrent transaction: the
    single-root one when it won the root race after `_check_no_other_root`
    passed, the parent reference when it deleted the parent after
    `require_reference` checked it (ADR 0048). A write setting no parent
    passes an empty `parent_reference`, since a null key cannot violate it."""
    return integrity.guard_constraints(
        session, {UQ_ORG_UNIT_SINGLE_ROOT: DuplicateRootError(OrgUnit), **parent_reference}
    )


async def create_org_unit(session: AsyncSession, data: OrgUnitCreate) -> OrgUnit:
    parent_reference = {}
    if data.parent_id is not None:
        parent_reference = await existence.require_reference(session, OrgUnit, data.parent_id, FK_ORG_UNIT_PARENT_ID)
    else:
        await _check_no_other_root(session)
    org_unit = OrgUnit(**data.model_dump())
    async with _write_race_guard(session, parent_reference):
        session.add(org_unit)
    return org_unit


async def list_org_units(session: AsyncSession, *, parent_id: list[int] | None = None) -> Sequence[OrgUnit]:
    stmt = select(OrgUnit).order_by(OrgUnit.id)
    if parent_id:
        stmt = stmt.where(OrgUnit.parent_id.in_(parent_id))
    result = await session.execute(stmt)
    return result.scalars().all()


async def get_org_unit(session: AsyncSession, org_unit_id: int) -> OrgUnit:
    return await existence.get_by_pk(session, OrgUnit, org_unit_id)


# One key for the whole tree: a narrower key would come from reading the tree,
# and that read is what races (ADR 0047).
async def _acquire_reparent_lock(session: AsyncSession) -> None:
    await session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(_REPARENT_LOCK_KEY, 0))))


async def update_org_unit(session: AsyncSession, org_unit_id: int, data: OrgUnitUpdate) -> OrgUnit:
    updates = data.model_dump(exclude_unset=True)
    is_reparent = "parent_id" in updates
    if is_reparent:
        # Ahead of the load, so the old parent, the ancestry check and the
        # write all read the tree the previous reparent committed.
        await _acquire_reparent_lock(session)
    # populate_existing, because a unit this session loaded before the lock
    # would otherwise keep the parent it read then. The row lock is the one
    # the UPDATE takes anyway, taken at the load so a concurrent delete is
    # waited out and read as not found (ADR 0048).
    fresh = select(OrgUnit).where(OrgUnit.id == org_unit_id).execution_options(populate_existing=True)
    if updates:
        fresh = fresh.with_for_update(key_share=True)
    org_unit = await existence.get_by_query(session, OrgUnit, fresh, org_unit_id)
    old_parent_id = org_unit.parent_id
    parent_reference = {}
    if is_reparent:
        new_parent_id = updates["parent_id"]
        if new_parent_id is not None:
            parent_reference = await existence.require_reference(session, OrgUnit, new_parent_id, FK_ORG_UNIT_PARENT_ID)
            # The subtree is inclusive of the unit itself, so self-parenting
            # and descendant-parenting fail as one membership check.
            if new_parent_id in await get_descendant_ids(session, [org_unit_id]):
                raise CircularReferenceError(OrgUnit, org_unit_id, new_parent_id)
        else:
            await _check_no_other_root(session, promoted_id=org_unit_id)
    async with _write_race_guard(session, parent_reference):
        for field, value in updates.items():
            setattr(org_unit, field, value)
    # Only after a write: with none, the row was read unlocked, and a refresh
    # would fail unmapped on one deleted since (ADR 0048).
    if updates:
        await session.refresh(org_unit)
    if is_reparent and org_unit.parent_id != old_parent_id:
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
# `integrity.guard_constraints` turns the violation into `HasDependentsError`.
async def delete_org_unit(session: AsyncSession, org_unit_id: int) -> None:
    org_unit = await get_org_unit(session, org_unit_id)
    # One instance for all three dependent FKs: `guard_constraints` raises at
    # most once per call.
    dependents = HasDependentsError(OrgUnit, org_unit_id)
    async with integrity.guard_constraints(
        session,
        {
            FK_ORG_UNIT_PARENT_ID: dependents,
            FK_APP_ORG_UNIT_ID: dependents,
            FK_SCORE_SNAPSHOT_ORG_UNIT_ID: dependents,
        },
    ):
        await session.delete(org_unit)
