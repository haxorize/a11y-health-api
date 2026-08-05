"""The Owner Dispatcher: the one module where per-Owner variation lives.

The `OWNERS` spec table is derived from one exhaustive match over
`ScoreSnapshotOwnerType`, so a missing owner case fails type checking. The
table is also the sanctioned test seam (ADR 0037): the rollup-race harness
swaps the whole table for a test's duration, and consumers resolve it at call
time.

See `docs/architecture.md` ("The scoring & rollup model").
"""

from collections.abc import Awaitable, Callable, Mapping
from types import MappingProxyType
from typing import NamedTuple, assert_never

from sqlalchemy import ColumnElement, Select, false, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from a11y_health.core import existence
from a11y_health.core.pagination import DEFAULT_PAGE_SIZE, CursorPage, paginate
from a11y_health.models.app import App
from a11y_health.models.brand import Brand
from a11y_health.models.enums import ScoreSnapshotOwnerType
from a11y_health.models.org_unit import OrgUnit
from a11y_health.models.score_snapshot import (
    UQ_SCORE_SNAPSHOT_BRAND_SNAPSHOT_AT,
    UQ_SCORE_SNAPSHOT_ORG_UNIT_SNAPSHOT_AT,
    ScoreSnapshot,
)
from a11y_health.services._latest_snapshot import select_latest_snapshots
from a11y_health.services._org_subtree import get_descendant_ids

type ChildrenRead = Callable[[AsyncSession, int], Awaitable[list[ScoreSnapshot]]]
type ParentLookup = Callable[[AsyncSession, int], Awaitable[int | None]]


# The one Brand-membership predicate: App.brand_id alone decides, wherever the
# app sits in the org tree. Shared by the brand scope and the Brand Rollup's
# children read.
def brand_apps(brand_id: int) -> Select[tuple[int]]:
    return select(App.id).where(App.brand_id == brand_id)


async def _latest_child_snapshots(session: AsyncSession, org_unit_id: int) -> list[ScoreSnapshot]:
    app_child = select(ScoreSnapshot).join(App, ScoreSnapshot.app_id == App.id).where(App.org_unit_id == org_unit_id)
    ou_child = (
        select(ScoreSnapshot)
        .join(OrgUnit, ScoreSnapshot.org_unit_id == OrgUnit.id)
        .where(OrgUnit.parent_id == org_unit_id)
    )
    stmt = select_latest_snapshots(
        app_child.union_all(ou_child), partition_on=[ScoreSnapshot.app_id, ScoreSnapshot.org_unit_id]
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _latest_brand_app_snapshots(session: AsyncSession, brand_id: int) -> list[ScoreSnapshot]:
    snapshots = select(ScoreSnapshot).where(ScoreSnapshot.app_id.in_(brand_apps(brand_id)))
    stmt = select_latest_snapshots(snapshots, partition_on=[ScoreSnapshot.app_id])
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _org_unit_parent(session: AsyncSession, org_unit_id: int) -> int | None:
    return (await existence.get_by_pk(session, OrgUnit, org_unit_id)).parent_id


# NamedTuples, not frozen dataclasses: a dataclass field typed
# InstrumentedAttribute gets descriptor-typed-field semantics from the type
# checker, so id_column would read back as `int | None`. NamedTuple fields
# don't; substitution uses `_replace` instead of `dataclasses.replace`.
class RollupSpec(NamedTuple):
    unique_index: str
    children: ChildrenRead
    cascade_parent: ParentLookup | None


class OwnerSpec(NamedTuple):
    owner_type: ScoreSnapshotOwnerType
    id_column: InstrumentedAttribute[int | None]
    entity: type[App] | type[OrgUnit] | type[Brand]
    # None: APP snapshots come from scoring, never a rollup.
    rollup: RollupSpec | None


def _spec_for(owner_type: ScoreSnapshotOwnerType) -> OwnerSpec:
    match owner_type:
        case ScoreSnapshotOwnerType.APP:
            return OwnerSpec(owner_type, ScoreSnapshot.app_id, App, None)
        case ScoreSnapshotOwnerType.ORG_UNIT:
            return OwnerSpec(
                owner_type,
                ScoreSnapshot.org_unit_id,
                OrgUnit,
                RollupSpec(UQ_SCORE_SNAPSHOT_ORG_UNIT_SNAPSHOT_AT, _latest_child_snapshots, _org_unit_parent),
            )
        case ScoreSnapshotOwnerType.BRAND:
            return OwnerSpec(
                owner_type,
                ScoreSnapshot.brand_id,
                Brand,
                RollupSpec(UQ_SCORE_SNAPSHOT_BRAND_SNAPSHOT_AT, _latest_brand_app_snapshots, None),
            )
        case _:
            assert_never(owner_type)


OWNERS: Mapping[ScoreSnapshotOwnerType, OwnerSpec] = MappingProxyType(
    {owner_type: _spec_for(owner_type) for owner_type in ScoreSnapshotOwnerType}
)


async def list_latest_scores(
    session: AsyncSession,
    owner_type: ScoreSnapshotOwnerType,
    *,
    owner_id: list[int] | None = None,
    brand_id: int | None = None,
    under_org_unit_id: int | None = None,
    direct_only: bool = False,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> CursorPage[ScoreSnapshot]:
    owner_col = OWNERS[owner_type].id_column
    snapshots = select(ScoreSnapshot).where(owner_col.is_not(None))
    if brand_id is not None:
        await existence.get_by_pk(session, Brand, brand_id)
        snapshots = snapshots.where(_brand_scope(owner_type, owner_col, brand_id))
    if under_org_unit_id is not None:
        await existence.get_by_pk(session, OrgUnit, under_org_unit_id)
        snapshots = snapshots.where(
            await _under_org_unit_scope(session, owner_type, owner_col, under_org_unit_id, direct_only)
        )
    if owner_id:
        # Exact-match, unlike list_apps' descendant-expanding org_unit_id: a rollup
        # owner's snapshot already aggregates everything it covers (an org unit's
        # subtree, a brand's flat app set), so expansion would double-count.
        snapshots = snapshots.where(owner_col.in_(owner_id))
    stmt = select_latest_snapshots(snapshots, partition_on=[owner_col])
    # Keyset on the owner id alone: it is unique here (one row per owner), never
    # NULL (the filter above), and an owner's position can't move when the latest
    # view recomputes between requests. Keying on snapshot_at — or adding the
    # usual id tiebreak — would let a mid-walk import re-serve an already-served
    # owner (its new latest row compares greater than the cursor) or hide one.
    return await paginate(
        session,
        stmt,
        keyset=[owner_col],
        cursor=cursor,
        limit=limit,
    )


def _brand_scope(
    owner_type: ScoreSnapshotOwnerType, owner_col: InstrumentedAttribute[int | None], brand_id: int
) -> ColumnElement[bool]:
    if owner_type is ScoreSnapshotOwnerType.APP:
        # Brand ownership is flat, like the brand rollup: the one membership
        # predicate decides, wherever the app sits in the org tree.
        return owner_col.in_(brand_apps(brand_id))
    if owner_type is ScoreSnapshotOwnerType.ORG_UNIT or owner_type is ScoreSnapshotOwnerType.BRAND:
        # Only apps carry brand ownership. An org unit has no brand, and a
        # brand isn't owned by a brand — the scoping brand's own rollup
        # already aggregates the scoped app set (fetch it via owner_id),
        # mirroring the under-scope's "not under itself". Empty, not "all".
        return false()
    assert_never(owner_type)


async def _under_org_unit_scope(
    session: AsyncSession,
    owner_type: ScoreSnapshotOwnerType,
    owner_col: InstrumentedAttribute[int | None],
    under_org_unit_id: int,
    direct_only: bool,
) -> ColumnElement[bool]:
    if owner_type is ScoreSnapshotOwnerType.APP:
        # An app placed anywhere in the subtree — including on the named unit
        # itself — is "under" it, matching list_apps' org_unit_id expansion.
        # direct_only is that same rule over the one-unit subtree.
        unit_ids = {under_org_unit_id} if direct_only else await get_descendant_ids(session, [under_org_unit_id])
        return owner_col.in_(select(App.id).where(App.org_unit_id.in_(unit_ids)))
    if owner_type is ScoreSnapshotOwnerType.ORG_UNIT:
        if direct_only:
            # Depth-1 needs no subtree walk: direct children are one
            # parent_id predicate.
            return owner_col.in_(select(OrgUnit.id).where(OrgUnit.parent_id == under_org_unit_id))
        # Strictly below: the named unit is not under itself, and its own
        # rollup already aggregates the subtree being scoped to.
        subtree = await get_descendant_ids(session, [under_org_unit_id])
        return owner_col.in_(subtree - {under_org_unit_id})
    if owner_type is ScoreSnapshotOwnerType.BRAND:
        # Brands have no org-tree placement, so no brand owner is ever
        # "under" an org unit — the honest scoped set is empty, not "all",
        # and no subtree query is worth running to say so.
        return false()
    assert_never(owner_type)


async def list_scores(
    session: AsyncSession,
    owner_type: ScoreSnapshotOwnerType,
    owner_id: int,
    *,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    descending: bool = False,
) -> CursorPage[ScoreSnapshot]:
    spec = OWNERS[owner_type]
    await existence.get_by_pk(session, spec.entity, owner_id)
    stmt = select(ScoreSnapshot).where(spec.id_column == owner_id)
    return await paginate(
        session,
        stmt,
        keyset=[ScoreSnapshot.snapshot_at, ScoreSnapshot.id],
        cursor=cursor,
        limit=limit,
        descending=descending,
    )
