from collections.abc import Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.score_snapshot import ScoreSnapshot


async def _list_scores(
    session: AsyncSession,
    filter_col: Any,
    filter_val: int,
    *,
    offset: int = 0,
    limit: int = 20,
) -> Sequence[ScoreSnapshot]:
    result = await session.execute(
        select(ScoreSnapshot)
        .where(filter_col == filter_val)
        .order_by(ScoreSnapshot.snapshot_at, ScoreSnapshot.id)
        .offset(offset)
        .limit(limit)
    )
    return result.scalars().all()


async def list_app_scores(
    session: AsyncSession, app_id: int, *, offset: int = 0, limit: int = 20
) -> Sequence[ScoreSnapshot]:
    from a11y_health.services.app import get_app

    await get_app(session, app_id)
    return await _list_scores(session, ScoreSnapshot.app_id, app_id, offset=offset, limit=limit)


async def list_brand_scores(
    session: AsyncSession, brand_id: int, *, offset: int = 0, limit: int = 20
) -> Sequence[ScoreSnapshot]:
    from a11y_health.services.brand import get_brand

    await get_brand(session, brand_id)
    return await _list_scores(session, ScoreSnapshot.brand_id, brand_id, offset=offset, limit=limit)


async def list_org_unit_scores(
    session: AsyncSession, org_unit_id: int, *, offset: int = 0, limit: int = 20
) -> Sequence[ScoreSnapshot]:
    from a11y_health.services.org_unit import get_org_unit

    await get_org_unit(session, org_unit_id)
    return await _list_scores(session, ScoreSnapshot.org_unit_id, org_unit_id, offset=offset, limit=limit)
