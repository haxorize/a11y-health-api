from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import assert_error, make_app, make_brand, make_org_unit


async def test_create_org_unit(db_client: AsyncClient, db_session: AsyncSession) -> None:
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
    # db_client shares one session across requests; expiring it makes the GET
    # read the row, as production's per-request session would.
    db_session.expire_all()
    fetched = await db_client.get(f"/api/v1/org-units/{data['id']}")
    assert data == fetched.json()


async def test_create_org_unit_with_invalid_parent(db_client: AsyncClient) -> None:
    response = await db_client.post(
        "/api/v1/org-units",
        json={"name": "Orphan", "parent_id": 999999},
    )
    assert response.status_code == 404


async def test_create_second_root_returns_409(db_client: AsyncClient, db_session: AsyncSession) -> None:
    await make_org_unit(db_session, name="Humana")
    response = await db_client.post("/api/v1/org-units", json={"name": "Shadow Humana"})
    assert_error(response, 409, "duplicate_root", message_contains="top-level")


async def test_list_org_units(db_client: AsyncClient, db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    await make_org_unit(db_session, name="CenterWell", parent_id=root.id)

    response = await db_client.get("/api/v1/org-units")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2


async def test_list_org_units_filtered_by_parent(db_client: AsyncClient, db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    child = await make_org_unit(db_session, name="CenterWell", parent_id=root.id)
    await make_org_unit(db_session, name="Primary Care", parent_id=child.id)

    response = await db_client.get("/api/v1/org-units", params={"parent_id": root.id})
    assert response.status_code == 200
    assert [ou["id"] for ou in response.json()] == [child.id]


async def test_list_org_units_filtered_by_several_parents(db_client: AsyncClient, db_session: AsyncSession) -> None:
    # Repeated parent_id decodes to a list and unions the children — the same
    # multi-value filter shape the apps listing uses.
    root = await make_org_unit(db_session, name="Humana")
    left = await make_org_unit(db_session, name="CenterWell", parent_id=root.id)
    right = await make_org_unit(db_session, name="Pharmacy", parent_id=root.id)
    left_child = await make_org_unit(db_session, name="Primary Care", parent_id=left.id)
    right_child = await make_org_unit(db_session, name="Mail Order", parent_id=right.id)

    response = await db_client.get("/api/v1/org-units", params={"parent_id": [left.id, right.id]})

    assert response.status_code == 200
    assert [ou["id"] for ou in response.json()] == [left_child.id, right_child.id]


async def test_list_org_units_filtered_by_unknown_parent_is_empty(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    # parent_id is a filter, so an unknown parent narrows to nothing rather
    # than 404ing, matching the apps listing's org_unit_id filter.
    await make_org_unit(db_session, name="Humana")

    response = await db_client.get("/api/v1/org-units", params={"parent_id": 999999})

    assert response.status_code == 200
    assert response.json() == []


async def test_get_org_unit(db_client: AsyncClient, db_session: AsyncSession) -> None:
    parent = await make_org_unit(db_session, name="Humana")
    org_unit = await make_org_unit(db_session, name="CenterWell", parent_id=parent.id)

    response = await db_client.get(f"/api/v1/org-units/{org_unit.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "CenterWell"
    assert data["parent_id"] == parent.id


async def test_get_org_unit_not_found(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/org-units/999999")
    assert response.status_code == 404


async def test_update_org_unit(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session, name="Humana")

    response = await db_client.patch(
        f"/api/v1/org-units/{org_unit.id}",
        json={"name": "Humana Inc."},
    )
    assert response.status_code == 200
    assert response.json()["name"] == "Humana Inc."


async def test_update_org_unit_refuses_a_null_name(db_client: AsyncClient, db_session: AsyncSession) -> None:
    # Red when OrgUnitUpdate.name admits None: the null reaches the NOT NULL
    # column and the unmapped violation is a 500.
    org_unit = await make_org_unit(db_session, name="Humana")

    response = await db_client.patch(f"/api/v1/org-units/{org_unit.id}", json={"name": None})

    assert response.status_code == 422
    assert (await db_client.get(f"/api/v1/org-units/{org_unit.id}")).json()["name"] == "Humana"


async def test_update_org_unit_without_a_name_keeps_it(db_client: AsyncClient, db_session: AsyncSession) -> None:
    parent = await make_org_unit(db_session, name="Humana")
    child = await make_org_unit(db_session, name="Pharmacy", parent_id=parent.id)
    other = await make_org_unit(db_session, name="Clinical", parent_id=parent.id)

    response = await db_client.patch(f"/api/v1/org-units/{child.id}", json={"parent_id": other.id})

    assert response.status_code == 200
    assert response.json()["name"] == "Pharmacy"


async def test_update_org_unit_not_found(db_client: AsyncClient) -> None:
    response = await db_client.patch(
        "/api/v1/org-units/999999",
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
    response = await db_client.delete("/api/v1/org-units/999999")
    assert response.status_code == 404


async def test_get_ancestors(db_client: AsyncClient, db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    child = await make_org_unit(db_session, name="CenterWell", parent_id=root.id)
    grandchild = await make_org_unit(db_session, name="Primary Care", parent_id=child.id)

    response = await db_client.get(f"/api/v1/org-units/{grandchild.id}/ancestors")
    assert response.status_code == 200
    ids = [a["id"] for a in response.json()]
    assert ids == [child.id, root.id]


async def test_get_ancestors_not_found(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/org-units/999999/ancestors")
    assert response.status_code == 404


async def test_update_rejects_circular_parent(db_client: AsyncClient, db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    child = await make_org_unit(db_session, name="CenterWell", parent_id=root.id)

    response = await db_client.patch(
        f"/api/v1/org-units/{root.id}",
        json={"parent_id": child.id},
    )
    assert_error(response, 409, "circular_reference", message_contains="circular reference")


async def test_reparent_to_parentless_returns_409(db_client: AsyncClient, db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    child = await make_org_unit(db_session, name="CenterWell", parent_id=root.id)
    response = await db_client.patch(f"/api/v1/org-units/{child.id}", json={"parent_id": None})
    assert_error(response, 409, "duplicate_root", message_contains="top-level")


async def test_delete_org_unit_with_apps(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session, name="Humana")
    brand = await make_brand(db_session)
    await make_app(db_session, name="MyHumana", slug="myhumana", brand_id=brand.id, org_unit_id=org_unit.id)

    response = await db_client.delete(f"/api/v1/org-units/{org_unit.id}")
    assert_error(response, 409, "has_dependents", message_contains="dependent")
