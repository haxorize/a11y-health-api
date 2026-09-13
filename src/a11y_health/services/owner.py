"""The Owner Dispatcher: the one module where per-Owner variation lives.

The `OWNERS` spec table is derived from one exhaustive match over
`ScoreSnapshotOwnerType`, so a missing owner case fails type checking. The
table is also the sanctioned test seam (ADR 0037): the rollup-race harness
swaps the whole table for a test's duration, and consumers resolve it at call
time.

App-score computation stays outside the charter, in `score_snapshot.py`; it
produces the `ScoreAggregates` value defined here, which is snapshot
vocabulary the dispatcher owns, not per-owner variation (ADR 0037, #136
amendment). See `docs/architecture.md` ("The scoring & rollup model").
"""

from collections.abc import Awaitable, Callable, Iterable, Mapping
from datetime import datetime
from math import fsum
from types import MappingProxyType
from typing import NamedTuple, assert_never

from sqlalchemy import ColumnElement, CompoundSelect, Select, delete, false, func, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from a11y_health.core import existence, integrity
from a11y_health.core.exceptions import ConcurrentRollupError
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
from a11y_health.services._org_subtree import select_descendant_ids

type ChildrenRead = Callable[[AsyncSession, int], Awaitable[list[ScoreSnapshot]]]
type ParentLookup = Callable[[AsyncSession, int], Awaitable[int | None]]


# The one Brand-membership predicate: App.brand_id alone decides, wherever the
# app sits in the org tree. Shared by the brand scope and the Brand Rollup's
# children read.
def brand_apps(brand_id: int) -> Select[tuple[int]]:
    return select(App.id).where(App.brand_id == brand_id)


async def _latest_of(
    session: AsyncSession, snapshots: Select | CompoundSelect, partition_on: list[InstrumentedAttribute]
) -> list[ScoreSnapshot]:
    result = await session.execute(select_latest_snapshots(snapshots, partition_on=partition_on))
    return list(result.scalars().all())


async def _latest_child_snapshots(session: AsyncSession, org_unit_id: int) -> list[ScoreSnapshot]:
    app_child = select(ScoreSnapshot).join(App, ScoreSnapshot.app_id == App.id).where(App.org_unit_id == org_unit_id)
    ou_child = (
        select(ScoreSnapshot)
        .join(OrgUnit, ScoreSnapshot.org_unit_id == OrgUnit.id)
        .where(OrgUnit.parent_id == org_unit_id)
    )
    return await _latest_of(
        session, app_child.union_all(ou_child), partition_on=[ScoreSnapshot.app_id, ScoreSnapshot.org_unit_id]
    )


async def _latest_brand_app_snapshots(session: AsyncSession, brand_id: int) -> list[ScoreSnapshot]:
    snapshots = select(ScoreSnapshot).where(ScoreSnapshot.app_id.in_(brand_apps(brand_id)))
    return await _latest_of(session, snapshots, partition_on=[ScoreSnapshot.app_id])


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
        snapshots = snapshots.where(_brand_scope(owner_type, brand_id))
    if under_org_unit_id is not None:
        await existence.get_by_pk(session, OrgUnit, under_org_unit_id)
        snapshots = snapshots.where(_under_org_unit_scope(owner_type, under_org_unit_id, direct_only))
    if owner_id is not None:
        # Exact-match, unlike list_apps' org_unit_id filter, which expands to
        # the subtree unless direct_only: a rollup owner's snapshot already
        # aggregates everything it covers (an org unit's subtree, a brand's
        # flat app set), so expansion would double-count. Any future
        # owner-valued filter on a scores read follows this exact-match side.
        snapshots = snapshots.where(owner_col.in_(owner_id))
    stmt = select_latest_snapshots(snapshots, partition_on=[owner_col])
    # Keyset on the owner id alone: it is unique here (one row per owner),
    # never NULL (the filter above), and an owner's position can't move when
    # the latest view recomputes between requests. Keying on snapshot_at — or
    # adding the usual id tiebreak — would let a mid-walk import re-serve an
    # already-served owner (its new latest row compares greater than the
    # cursor) or hide one.
    return await paginate(
        session,
        stmt,
        keyset=[owner_col],
        cursor=cursor,
        limit=limit,
    )


def _brand_scope(owner_type: ScoreSnapshotOwnerType, brand_id: int) -> ColumnElement[bool]:
    if owner_type is ScoreSnapshotOwnerType.APP:
        # Brand ownership is flat, like the brand rollup: the one membership
        # predicate decides, wherever the app sits in the org tree.
        return OWNERS[owner_type].id_column.in_(brand_apps(brand_id))
    if owner_type is ScoreSnapshotOwnerType.ORG_UNIT or owner_type is ScoreSnapshotOwnerType.BRAND:
        # Only apps carry brand ownership. An org unit has no brand, and a
        # brand isn't owned by a brand — the scoping brand's own rollup
        # already aggregates the scoped app set (fetch it via owner_id),
        # mirroring the under-scope's "not under itself". Empty, not "all".
        return false()
    assert_never(owner_type)


def _under_org_unit_scope(
    owner_type: ScoreSnapshotOwnerType,
    under_org_unit_id: int,
    direct_only: bool,
) -> ColumnElement[bool]:
    owner_col = OWNERS[owner_type].id_column
    if owner_type is ScoreSnapshotOwnerType.APP:
        # An app placed anywhere in the subtree — including on the named unit
        # itself — is "under" it, matching list_apps' org_unit_id expansion.
        # direct_only is that same rule over the one-unit subtree.
        unit_scope = [under_org_unit_id] if direct_only else select_descendant_ids([under_org_unit_id])
        return owner_col.in_(select(App.id).where(App.org_unit_id.in_(unit_scope)))
    if owner_type is ScoreSnapshotOwnerType.ORG_UNIT:
        if direct_only:
            # Depth-1 needs no subtree walk: direct children are one
            # parent_id predicate.
            return owner_col.in_(select(OrgUnit.id).where(OrgUnit.parent_id == under_org_unit_id))
        # Strictly below: the named unit is not under itself, and its own
        # rollup already aggregates the subtree being scoped to.
        return owner_col.in_(select_descendant_ids([under_org_unit_id])) & (owner_col != under_org_unit_id)
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


# Score Aggregates (DOMAIN.md): the Score and raw counts a Score Snapshot
# summarizes, and the equality basis for the same-observation dedupe — every
# aggregate the snapshot carries and nothing else (observation time is time,
# not an aggregate). The field list here is the one definition: `owned` writes
# it and `from_snapshot` reads it, both by name. A column-set canary test pins
# the model so adding a column forces a decision on whether it joins this
# value. Deriving the set from the mapper was tried and reverted (6b721f1): the
# deny-list it needs drifts silently, and the canary carries the drift-proofing
# instead.
#
# The wire echoes these fields as `schemas.score_snapshot.ScoreAggregatesRead`,
# and a test pins the two together; the field order here follows the model
# column order and the wire, so a positional construction carrying either
# order is right.
class ScoreAggregates(NamedTuple):
    score: float
    total_violations: int
    pages_with_violations: int
    pages_with_critical_violations: int
    total_pages: int

    @classmethod
    def from_snapshot(cls, snapshot: ScoreSnapshot) -> ScoreAggregates:
        return cls._make(getattr(snapshot, field) for field in cls._fields)

    # Mean of the children's Scores, sums of their counts (DOMAIN.md, Rollup).
    # `fsum` is exactly rounded, so the mean is the same in whatever order the
    # latest-child query returned the children — a recompute is
    # bitwise-reproducible, which the no-change skip in `_apply_rollup` relies
    # on when it compares the result for equality.
    @classmethod
    def rolled_up(cls, children: Iterable[ScoreAggregates]) -> ScoreAggregates:
        items = list(children)
        if not items:
            raise ValueError("a rollup needs at least one child")
        return cls(
            score=fsum(c.score for c in items) / len(items),
            total_violations=sum(c.total_violations for c in items),
            total_pages=sum(c.total_pages for c in items),
            pages_with_violations=sum(c.pages_with_violations for c in items),
            pages_with_critical_violations=sum(c.pages_with_critical_violations for c in items),
        )


def owned(
    owner_type: ScoreSnapshotOwnerType,
    owner_id: int,
    aggregates: ScoreAggregates,
    *,
    scan_run_id: int | None = None,
    snapshot_at: datetime,
) -> ScoreSnapshot:
    """Exactly-one-owner is structural — the spec picks the column, and the
    database check constraint stays as the backstop. Raises `ValueError` when a
    Scan Run is linked to a non-App owner: only App snapshots come from
    scans."""
    if scan_run_id is not None and owner_type is not ScoreSnapshotOwnerType.APP:
        raise ValueError("scan_run_id requires an APP owner")
    return ScoreSnapshot(
        scan_run_id=scan_run_id,
        snapshot_at=snapshot_at,
        **aggregates._asdict(),
        **{OWNERS[owner_type].id_column.key: owner_id},
    )


_DEADLOCK_SQLSTATE = "40P01"


def _require_rollup_spec(owner_type: ScoreSnapshotOwnerType) -> tuple[OwnerSpec, RollupSpec]:
    spec = OWNERS[owner_type]
    if spec.rollup is None:
        raise ValueError(f"{owner_type.value} snapshots come from scoring, not a rollup")
    return spec, spec.rollup


def _concurrent_rollup_error(owner_type: ScoreSnapshotOwnerType, owner_id: int) -> ConcurrentRollupError:
    return ConcurrentRollupError(existence.ENTITY_LABELS[OWNERS[owner_type].entity], owner_id)


# The #98 indexes allow at most one match; the id-desc pick mirrors the Latest
# Score Snapshot tie-break as a belt for pre-enforcement databases.
async def _snapshot_recorded_at_observation(
    session: AsyncSession, owner: ColumnElement[bool], snapshot_at: datetime
) -> ScoreSnapshot | None:
    return (
        await session.execute(
            select(ScoreSnapshot)
            .where(owner, ScoreSnapshot.snapshot_at == snapshot_at)
            .order_by(ScoreSnapshot.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _apply_rollup(
    session: AsyncSession,
    children: list[ScoreSnapshot],
    spec: OwnerSpec,
    rollup_spec: RollupSpec,
    owner_id: int,
) -> None:
    criterion = spec.id_column == owner_id
    # No children → nothing to aggregate; every snapshot the owner has is
    # orphaned.
    if not children:
        await session.execute(delete(ScoreSnapshot).where(criterion))
        return
    # Snapshots forward of the new max are orphaned — the data behind them is
    # gone — so prune.
    snapshot_at = max(c.snapshot_at for c in children)
    await session.execute(delete(ScoreSnapshot).where(criterion, ScoreSnapshot.snapshot_at > snapshot_at))
    aggregates = ScoreAggregates.rolled_up(ScoreAggregates.from_snapshot(c) for c in children)
    snapshot = owned(spec.owner_type, owner_id, aggregates, snapshot_at=snapshot_at)
    # One snapshot per distinct observation, not one per trigger (#95, ADR
    # 0015). A newer observation time always appends — even with unchanged
    # values — so the latest snapshot never claims an observation whose source
    # data is gone.
    existing = await _snapshot_recorded_at_observation(session, criterion, snapshot_at)
    if existing is not None:
        if ScoreAggregates.from_snapshot(existing) == aggregates:
            return
        await session.execute(delete(ScoreSnapshot).where(criterion, ScoreSnapshot.snapshot_at == snapshot_at))
    # The unique indexes (#98) only decide races: a concurrent rollup landing
    # between the read above and this insert makes the flush a violation.
    async with integrity.guard(
        session, {rollup_spec.unique_index: _concurrent_rollup_error(spec.owner_type, owner_id)}
    ):
        session.add(snapshot)


# Different-observation interleavings never collide on a row, so serializing
# them takes a lock, not a constraint — transaction-scoped, acquired as the
# rollup's first statement so the children read and the writes sit under one
# serialization (ADR 0029). Hashing the key avoids int4 overflow on BIGINT
# owner ids; a collision merely over-serializes.
async def _acquire_rollup_lock(session: AsyncSession, owner_type: ScoreSnapshotOwnerType, owner_id: int) -> None:
    key = func.hashtextextended(f"rollup:{owner_type.value}:{owner_id}", 0)
    try:
        await session.execute(select(func.pg_advisory_xact_lock(key)))
    except DBAPIError as exc:
        # A deadlock victim's 40P01 lands on the statement that was waiting —
        # this one (ADR 0029) — and the loser is semantically a
        # concurrent-rollup loser (#104). Anything else propagates unchanged,
        # as in ADR 0028.
        if getattr(exc.orig, "sqlstate", None) != _DEADLOCK_SQLSTATE:
            raise
        raise _concurrent_rollup_error(owner_type, owner_id) from exc


async def rollup(session: AsyncSession, owner_type: ScoreSnapshotOwnerType, owner_id: int) -> None:
    """Recompute the owner's aggregate from its children's latest snapshots,
    cascading to the parent where the spec defines one. Raises `ValueError` for
    an owner type that doesn't roll up (APP)."""
    spec, rollup_spec = _require_rollup_spec(owner_type)
    await _acquire_rollup_lock(session, owner_type, owner_id)
    children = await rollup_spec.children(session, owner_id)
    await _apply_rollup(session, children, spec, rollup_spec, owner_id)

    if rollup_spec.cascade_parent is not None:
        parent_id = await rollup_spec.cascade_parent(session, owner_id)
        if parent_id is not None:
            await rollup(session, owner_type, parent_id)
