from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.pagination import CursorPage, paginate
from a11y_health.models.score_snapshot import ScoreSnapshot


async def _list_scores(
    session: AsyncSession,
    filter_col: Any,
    filter_val: int,
    *,
    cursor: str | None = None,
    limit: int = 20,
) -> CursorPage[ScoreSnapshot]:
    stmt = select(ScoreSnapshot).where(filter_col == filter_val)
    return await paginate(
        session,
        stmt,
        keyset=[ScoreSnapshot.snapshot_at, ScoreSnapshot.id],
        cursor=cursor,
        limit=limit,
    )


async def list_app_scores(
    session: AsyncSession, app_id: int, *, cursor: str | None = None, limit: int = 20
) -> CursorPage[ScoreSnapshot]:
    from a11y_health.services.app import get_app

    await get_app(session, app_id)
    return await _list_scores(session, ScoreSnapshot.app_id, app_id, cursor=cursor, limit=limit)


async def list_brand_scores(
    session: AsyncSession, brand_id: int, *, cursor: str | None = None, limit: int = 20
) -> CursorPage[ScoreSnapshot]:
    from a11y_health.services.brand import get_brand

    await get_brand(session, brand_id)
    return await _list_scores(session, ScoreSnapshot.brand_id, brand_id, cursor=cursor, limit=limit)


async def list_org_unit_scores(
    session: AsyncSession, org_unit_id: int, *, cursor: str | None = None, limit: int = 20
) -> CursorPage[ScoreSnapshot]:
    from a11y_health.services.org_unit import get_org_unit

    await get_org_unit(session, org_unit_id)
    return await _list_scores(session, ScoreSnapshot.org_unit_id, org_unit_id, cursor=cursor, limit=limit)
