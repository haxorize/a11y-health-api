"""Reading Score Snapshots back out — the read side of scoring.

Paginated history listings for an App, Org Unit, or Brand — oldest first by
default, newest first on request (`descending`, the endpoints' `order=desc`) —
plus the cross-entity latest-per-owner read behind
`/scores/latest` (selection shared with the rollups via `_latest_snapshot.py`).
The computation that produces these snapshots lives in `score_snapshot.py`.

See `docs/architecture.md` ("The scoring & rollup model").
"""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core import existence
from a11y_health.core.pagination import DEFAULT_PAGE_SIZE, CursorPage, paginate
from a11y_health.models.app import App
from a11y_health.models.brand import Brand
from a11y_health.models.enums import ScoreSnapshotOwnerType
from a11y_health.models.org_unit import OrgUnit
from a11y_health.models.score_snapshot import OWNER_ID_COLUMNS, ScoreSnapshot
from a11y_health.services._latest_snapshot import select_latest_snapshots


async def list_latest_scores(
    session: AsyncSession,
    owner_type: ScoreSnapshotOwnerType,
    *,
    owner_id: list[int] | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> CursorPage[ScoreSnapshot]:
    owner_col = OWNER_ID_COLUMNS[owner_type]
    snapshots = select(ScoreSnapshot).where(owner_col.is_not(None))
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


async def _list_scores(
    session: AsyncSession,
    filter_col: Any,
    filter_val: int,
    *,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    descending: bool = False,
) -> CursorPage[ScoreSnapshot]:
    stmt = select(ScoreSnapshot).where(filter_col == filter_val)
    return await paginate(
        session,
        stmt,
        keyset=[ScoreSnapshot.snapshot_at, ScoreSnapshot.id],
        cursor=cursor,
        limit=limit,
        descending=descending,
    )


async def list_app_scores(
    session: AsyncSession,
    app_id: int,
    *,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    descending: bool = False,
) -> CursorPage[ScoreSnapshot]:
    await existence.get_by_pk(session, App, app_id)
    return await _list_scores(session, ScoreSnapshot.app_id, app_id, cursor=cursor, limit=limit, descending=descending)


async def list_brand_scores(
    session: AsyncSession,
    brand_id: int,
    *,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    descending: bool = False,
) -> CursorPage[ScoreSnapshot]:
    await existence.get_by_pk(session, Brand, brand_id)
    return await _list_scores(
        session, ScoreSnapshot.brand_id, brand_id, cursor=cursor, limit=limit, descending=descending
    )


async def list_org_unit_scores(
    session: AsyncSession,
    org_unit_id: int,
    *,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
    descending: bool = False,
) -> CursorPage[ScoreSnapshot]:
    await existence.get_by_pk(session, OrgUnit, org_unit_id)
    return await _list_scores(
        session, ScoreSnapshot.org_unit_id, org_unit_id, cursor=cursor, limit=limit, descending=descending
    )
