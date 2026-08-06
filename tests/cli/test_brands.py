from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.cli._client import list_brands
from tests.factories import make_brand


async def test_list_brands_returns_id_and_name(db_session: AsyncSession, db_client: AsyncClient) -> None:
    brand = await make_brand(db_session, name="Humana")

    rows = await list_brands(db_client)

    by_name = {row["name"]: row for row in rows}
    assert by_name["Humana"]["id"] == brand.id
