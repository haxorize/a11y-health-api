from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import NotFoundError
from a11y_health.models.brand import Brand

_RESOURCE = "Brand"


async def list_brands(session: AsyncSession) -> Sequence[Brand]:
    result = await session.execute(select(Brand).order_by(Brand.id))
    return result.scalars().all()


async def get_brand(session: AsyncSession, brand_id: int) -> Brand:
    brand = await session.get(Brand, brand_id)
    if brand is None:
        raise NotFoundError(_RESOURCE, brand_id)
    return brand
