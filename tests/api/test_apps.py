from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_app, make_brand, make_org_unit, make_scan_run, make_score_snapshot


async def test_create_app(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session, name="Humana")
    brand = await make_brand(db_session, name="Humana")

    response = await db_client.post(
        "/api/v1/apps",
        json={
            "name": "MyHumana",
            "slug": "myhumana",
            "brand_id": brand.id,
            "org_unit_id": org_unit.id,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "MyHumana"
    assert data["slug"] == "myhumana"
    assert data["brand_id"] == brand.id
    assert data["org_unit_id"] == org_unit.id
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data


async def test_create_app_invalid_brand(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    response = await db_client.post(
        "/api/v1/apps",
        json={
            "name": "MyHumana",
            "slug": "myhumana",
            "brand_id": 999999,
            "org_unit_id": org_unit.id,
        },
    )
    assert response.status_code == 404


async def test_create_app_invalid_org_unit(db_client: AsyncClient, db_session: AsyncSession) -> None:
    brand = await make_brand(db_session)
    response = await db_client.post(
        "/api/v1/apps",
        json={
            "name": "MyHumana",
            "slug": "myhumana",
            "brand_id": brand.id,
            "org_unit_id": 999999,
        },
    )
    assert response.status_code == 404


async def test_create_app_duplicate_slug(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session, name="Humana")
    brand = await make_brand(db_session, name="Humana")

    await db_client.post(
        "/api/v1/apps",
        json={"name": "MyHumana", "slug": "myhumana", "brand_id": brand.id, "org_unit_id": org_unit.id},
    )
    response = await db_client.post(
        "/api/v1/apps",
        json={"name": "MyHumana 2", "slug": "myhumana", "brand_id": brand.id, "org_unit_id": org_unit.id},
    )
    assert response.status_code == 409


async def test_list_apps(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)
    await make_app(db_session, name="MyHumana", slug="myhumana", brand_id=brand.id, org_unit_id=org_unit.id)
    await make_app(db_session, name="Go365 App", slug="go365", brand_id=brand.id, org_unit_id=org_unit.id)

    response = await db_client.get("/api/v1/apps")
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 2
    assert data["next_cursor"] is None
    slugs = {a["slug"] for a in data["items"]}
    assert slugs == {"myhumana", "go365"}


# Cursor pagination mechanics (limit, next_cursor, second-page round-trip) are proven
# centrally in tests/core/test_pagination.py. This endpoint test keeps only the generic
# InvalidCursorError -> 400 mapping, which has no other HTTP-layer home.
async def test_list_apps_invalid_cursor(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/apps", params={"cursor": "not-a-cursor"})
    assert response.status_code == 400


async def test_list_apps_filter_by_brand_id(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    humana = await make_brand(db_session, name="Humana")
    go365 = await make_brand(db_session, name="Go365")
    await make_app(db_session, name="MyHumana", slug="myhumana", brand_id=humana.id, org_unit_id=org_unit.id)
    await make_app(db_session, name="Go365 App", slug="go365", brand_id=go365.id, org_unit_id=org_unit.id)

    response = await db_client.get("/api/v1/apps", params={"brand_id": humana.id})
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["brand_id"] == humana.id


async def test_list_apps_filter_by_multiple_brand_ids(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    humana = await make_brand(db_session, name="Humana")
    go365 = await make_brand(db_session, name="Go365")
    centerwell = await make_brand(db_session, name="CenterWell")
    await make_app(db_session, slug="humana-app", brand_id=humana.id, org_unit_id=org_unit.id)
    await make_app(db_session, slug="go365-app", brand_id=go365.id, org_unit_id=org_unit.id)
    await make_app(db_session, slug="centerwell-app", brand_id=centerwell.id, org_unit_id=org_unit.id)

    response = await db_client.get("/api/v1/apps", params=[("brand_id", humana.id), ("brand_id", go365.id)])
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2
    brand_ids = {a["brand_id"] for a in items}
    assert brand_ids == {humana.id, go365.id}


async def test_list_apps_filter_by_org_unit_hierarchical(db_client: AsyncClient, db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    child = await make_org_unit(db_session, name="CenterWell", parent_id=root.id)
    other = await make_org_unit(db_session, name="Other")
    brand = await make_brand(db_session)
    await make_app(db_session, slug="root-app", brand_id=brand.id, org_unit_id=root.id)
    await make_app(db_session, slug="child-app", brand_id=brand.id, org_unit_id=child.id)
    await make_app(db_session, slug="other-app", brand_id=brand.id, org_unit_id=other.id)

    response = await db_client.get("/api/v1/apps", params={"org_unit_id": root.id})
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 2
    slugs = {a["slug"] for a in items}
    assert slugs == {"root-app", "child-app"}


async def test_list_apps_combined_brand_and_org_unit(db_client: AsyncClient, db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    child = await make_org_unit(db_session, name="CenterWell", parent_id=root.id)
    other = await make_org_unit(db_session, name="Other")
    humana = await make_brand(db_session, name="Humana")
    go365 = await make_brand(db_session, name="Go365")
    await make_app(db_session, slug="match", brand_id=humana.id, org_unit_id=child.id)
    await make_app(db_session, slug="wrong-brand", brand_id=go365.id, org_unit_id=child.id)
    await make_app(db_session, slug="wrong-org", brand_id=humana.id, org_unit_id=other.id)

    response = await db_client.get("/api/v1/apps", params={"brand_id": humana.id, "org_unit_id": root.id})
    assert response.status_code == 200
    items = response.json()["items"]
    assert len(items) == 1
    assert items[0]["slug"] == "match"


async def test_get_app(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)
    app = await make_app(db_session, name="MyHumana", slug="myhumana", brand_id=brand.id, org_unit_id=org_unit.id)

    response = await db_client.get(f"/api/v1/apps/{app.id}")
    assert response.status_code == 200
    assert response.json()["slug"] == "myhumana"


async def test_get_app_not_found(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/apps/999999")
    assert response.status_code == 404


async def test_get_app_by_slug(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)
    await make_app(db_session, name="MyHumana", slug="myhumana", brand_id=brand.id, org_unit_id=org_unit.id)

    response = await db_client.get("/api/v1/apps/slug/myhumana")
    assert response.status_code == 200
    assert response.json()["slug"] == "myhumana"


async def test_get_app_by_slug_not_found(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/apps/slug/nonexistent")
    assert response.status_code == 404


async def test_update_app_name(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)
    app = await make_app(db_session, name="MyHumana", slug="myhumana", brand_id=brand.id, org_unit_id=org_unit.id)

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
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)
    app = await make_app(db_session, name="MyHumana", slug="myhumana", brand_id=brand.id, org_unit_id=org_unit.id)

    response = await db_client.delete(f"/api/v1/apps/{app.id}")
    assert response.status_code == 204

    get_response = await db_client.get(f"/api/v1/apps/{app.id}")
    assert get_response.status_code == 404


async def test_delete_app_not_found(db_client: AsyncClient) -> None:
    response = await db_client.delete("/api/v1/apps/999999")
    assert response.status_code == 404


async def test_delete_app_cascades_dependents(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)
    app = await make_app(db_session, name="MyHumana", slug="myhumana", brand_id=brand.id, org_unit_id=org_unit.id)
    await make_scan_run(db_session, app_id=app.id)
    await make_score_snapshot(db_session, app_id=app.id)

    response = await db_client.delete(f"/api/v1/apps/{app.id}")
    assert response.status_code == 204

    get_response = await db_client.get(f"/api/v1/apps/{app.id}")
    assert get_response.status_code == 404
