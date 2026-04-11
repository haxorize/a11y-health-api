from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.enums import Brand
from tests.factories import make_app, make_org_unit, make_scan_run, make_score_snapshot


async def test_create_app(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session, name="Humana")

    response = await db_client.post(
        "/api/v1/apps",
        json={
            "name": "MyHumana",
            "slug": "myhumana",
            "brand": "Humana",
            "org_unit_id": org_unit.id,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "MyHumana"
    assert data["slug"] == "myhumana"
    assert data["brand"] == "Humana"
    assert data["org_unit_id"] == org_unit.id
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


async def test_create_app_invalid_org_unit(db_client: AsyncClient) -> None:
    response = await db_client.post(
        "/api/v1/apps",
        json={
            "name": "MyHumana",
            "slug": "myhumana",
            "brand": "Humana",
            "org_unit_id": 999999,
        },
    )
    assert response.status_code == 404


async def test_create_app_duplicate_slug(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session, name="Humana")

    await db_client.post(
        "/api/v1/apps",
        json={"name": "MyHumana", "slug": "myhumana", "brand": "Humana", "org_unit_id": org_unit.id},
    )
    response = await db_client.post(
        "/api/v1/apps",
        json={"name": "MyHumana 2", "slug": "myhumana", "brand": "Go365", "org_unit_id": org_unit.id},
    )
    assert response.status_code == 409


async def test_list_apps(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session, name="Humana")
    await make_app(db_session, name="MyHumana", slug="myhumana", brand=Brand.HUMANA, org_unit_id=org_unit.id)
    await make_app(db_session, name="Go365 App", slug="go365", brand=Brand.GO365, org_unit_id=org_unit.id)

    response = await db_client.get("/api/v1/apps")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    slugs = {a["slug"] for a in data}
    assert slugs == {"myhumana", "go365"}


async def test_list_apps_filter_by_brand(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session, name="Humana")
    await make_app(db_session, name="MyHumana", slug="myhumana", brand=Brand.HUMANA, org_unit_id=org_unit.id)
    await make_app(db_session, name="Go365 App", slug="go365", brand=Brand.GO365, org_unit_id=org_unit.id)

    response = await db_client.get("/api/v1/apps", params={"brand": "Humana"})
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["brand"] == "Humana"


async def test_get_app(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session, name="Humana")
    app = await make_app(db_session, name="MyHumana", slug="myhumana", brand=Brand.HUMANA, org_unit_id=org_unit.id)

    response = await db_client.get(f"/api/v1/apps/{app.id}")
    assert response.status_code == 200
    assert response.json()["slug"] == "myhumana"


async def test_get_app_not_found(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/apps/999999")
    assert response.status_code == 404


async def test_get_app_by_slug(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session, name="Humana")
    await make_app(db_session, name="MyHumana", slug="myhumana", brand=Brand.HUMANA, org_unit_id=org_unit.id)

    response = await db_client.get("/api/v1/apps/slug/myhumana")
    assert response.status_code == 200
    assert response.json()["slug"] == "myhumana"


async def test_get_app_by_slug_not_found(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/apps/slug/nonexistent")
    assert response.status_code == 404


async def test_update_app_name(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session, name="Humana")
    app = await make_app(db_session, name="MyHumana", slug="myhumana", brand=Brand.HUMANA, org_unit_id=org_unit.id)

    response = await db_client.patch(
        f"/api/v1/apps/{app.id}",
        json={"name": "MyHumana Redesign"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "MyHumana Redesign"
    assert data["slug"] == "myhumana"


async def test_update_app_not_found(db_client: AsyncClient) -> None:
    response = await db_client.patch(
        "/api/v1/apps/999999",
        json={"name": "Ghost"},
    )
    assert response.status_code == 404


async def test_delete_app(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session, name="Humana")
    app = await make_app(db_session, name="MyHumana", slug="myhumana", brand=Brand.HUMANA, org_unit_id=org_unit.id)

    response = await db_client.delete(f"/api/v1/apps/{app.id}")
    assert response.status_code == 204

    get_response = await db_client.get(f"/api/v1/apps/{app.id}")
    assert get_response.status_code == 404


async def test_delete_app_not_found(db_client: AsyncClient) -> None:
    response = await db_client.delete("/api/v1/apps/999999")
    assert response.status_code == 404


async def test_delete_app_with_scan_runs(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session, name="Humana")
    app = await make_app(db_session, name="MyHumana", slug="myhumana", brand=Brand.HUMANA, org_unit_id=org_unit.id)
    await make_scan_run(db_session, app_id=app.id)

    response = await db_client.delete(f"/api/v1/apps/{app.id}")
    assert response.status_code == 409
    assert "dependent" in response.json()["detail"].lower()


async def test_delete_app_with_score_snapshots(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session, name="Humana")
    app = await make_app(db_session, name="MyHumana", slug="myhumana", brand=Brand.HUMANA, org_unit_id=org_unit.id)
    await make_score_snapshot(db_session, app_id=app.id)

    response = await db_client.delete(f"/api/v1/apps/{app.id}")
    assert response.status_code == 409
    assert "dependent" in response.json()["detail"].lower()
