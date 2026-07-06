from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core import existence
from a11y_health.models.brand import Brand


async def list_brands(session: AsyncSession) -> Sequence[Brand]:
    result = await session.execute(select(Brand).order_by(Brand.id))
    return result.scalars().all()


async def get_brand(session: AsyncSession, brand_id: int) -> Brand:
    return await existence.get_by_pk(session, Brand, brand_id)
