"""The Owner Dispatcher: the one module where per-Owner variation lives.

The `OWNERS` spec table is derived from one exhaustive match over
`ScoreSnapshotOwnerType`, so a missing owner case fails type checking. The
table is also the sanctioned test seam (ADR 0037): the rollup-race harness
swaps the whole table for a test's duration, and consumers resolve it at call
time.

See `docs/architecture.md` ("The scoring & rollup model").
"""

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import assert_never

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from a11y_health.core import existence
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

type ChildrenRead = Callable[[AsyncSession, int], Awaitable[list[ScoreSnapshot]]]
type ParentLookup = Callable[[AsyncSession, int], Awaitable[int | None]]


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
    brand_apps = select(ScoreSnapshot).join(App, ScoreSnapshot.app_id == App.id).where(App.brand_id == brand_id)
    stmt = select_latest_snapshots(brand_apps, partition_on=[ScoreSnapshot.app_id])
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def _org_unit_parent(session: AsyncSession, org_unit_id: int) -> int | None:
    return (await existence.get_by_pk(session, OrgUnit, org_unit_id)).parent_id


@dataclass(frozen=True)
class RollupSpec:
    unique_index: str
    children: ChildrenRead
    cascade_parent: ParentLookup | None


@dataclass(frozen=True)
class OwnerSpec:
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
