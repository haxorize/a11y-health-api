from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_org_unit


async def test_create_org_unit(db_client: AsyncClient) -> None:
    response = await db_client.post(
        "/api/v1/org-units",
        json={"name": "Humana"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Humana"
    assert data["parent_id"] is None
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


async def test_create_org_unit_with_parent(db_client: AsyncClient, db_session: AsyncSession) -> None:
    parent = await make_org_unit(db_session, name="Humana")

    response = await db_client.post(
        "/api/v1/org-units",
        json={"name": "CenterWell", "parent_id": str(parent.id)},
    )
    assert response.status_code == 201
    assert response.json()["parent_id"] == str(parent.id)


async def test_create_org_unit_with_invalid_parent(db_client: AsyncClient) -> None:
    response = await db_client.post(
        "/api/v1/org-units",
        json={"name": "Orphan", "parent_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert response.status_code == 404


async def test_list_org_units(db_client: AsyncClient, db_session: AsyncSession) -> None:
    await make_org_unit(db_session, name="Humana")
    await make_org_unit(db_session, name="CenterWell")

    response = await db_client.get("/api/v1/org-units")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    names = {ou["name"] for ou in data}
    assert names == {"Humana", "CenterWell"}


async def test_get_org_unit(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session, name="Humana")

    response = await db_client.get(f"/api/v1/org-units/{org_unit.id}")
    assert response.status_code == 200
    assert response.json()["name"] == "Humana"


async def test_get_org_unit_not_found(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/org-units/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


async def test_update_org_unit(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session, name="Humana")

    response = await db_client.patch(
        f"/api/v1/org-units/{org_unit.id}",
        json={"name": "Humana Inc."},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Humana Inc."


async def test_update_org_unit_not_found(db_client: AsyncClient) -> None:
    response = await db_client.patch(
        "/api/v1/org-units/00000000-0000-0000-0000-000000000000",
        json={"name": "Ghost"},
    )
    assert response.status_code == 404


async def test_delete_org_unit(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session, name="Humana")

    response = await db_client.delete(f"/api/v1/org-units/{org_unit.id}")
    assert response.status_code == 204

    get_response = await db_client.get(f"/api/v1/org-units/{org_unit.id}")
    assert get_response.status_code == 404


async def test_delete_org_unit_not_found(db_client: AsyncClient) -> None:
    response = await db_client.delete("/api/v1/org-units/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404
