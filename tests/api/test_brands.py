from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_brand


async def test_list_brands(db_client: AsyncClient, db_session: AsyncSession) -> None:
    await make_brand(db_session, name="Humana")
    await make_brand(db_session, name="Go365")

    response = await db_client.get("/api/v1/brands")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    assert "id" in data[0]
    assert "created_at" in data[0]
    assert "updated_at" in data[0]


async def test_get_brand(db_client: AsyncClient, db_session: AsyncSession) -> None:
    brand = await make_brand(db_session, name="CenterWell")

    response = await db_client.get(f"/api/v1/brands/{brand.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == brand.id
    assert data["name"] == "CenterWell"


async def test_get_brand_not_found(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/brands/999999")
    assert response.status_code == 404
