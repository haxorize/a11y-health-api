import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import NotFoundError
from a11y_health.services import brand as brand_service
from tests.factories import make_brand


async def test_list_brands(db_session: AsyncSession) -> None:
    await make_brand(db_session, name="Humana")
    await make_brand(db_session, name="Go365")
    result = await brand_service.list_brands(db_session)
    assert len(result) == 2
    names = {b.name for b in result}
    assert names == {"Humana", "Go365"}


async def test_get_brand(db_session: AsyncSession) -> None:
    brand = await make_brand(db_session, name="Humana")
    fetched = await brand_service.get_brand(db_session, brand.id)
    assert fetched.id == brand.id
    assert fetched.name == "Humana"


async def test_get_brand_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError, match="Brand"):
        await brand_service.get_brand(db_session, 999999)
