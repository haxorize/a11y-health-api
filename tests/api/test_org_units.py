from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import ConcurrentRollupError
from a11y_health.services import score_snapshot as score_snapshot_service
from tests.factories import assert_error, make_app, make_brand, make_org_unit


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
    names = {ou["name"] for ou in data}
    assert names == {"Humana", "CenterWell"}


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


async def test_get_descendants(db_client: AsyncClient, db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    child = await make_org_unit(db_session, name="CenterWell", parent_id=root.id)
    grandchild = await make_org_unit(db_session, name="Primary Care", parent_id=child.id)

    response = await db_client.get(f"/api/v1/org-units/{root.id}/descendants")
    assert response.status_code == 200
    ids = {d["id"] for d in response.json()}
    assert ids == {child.id, grandchild.id}


async def test_get_descendants_not_found(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/org-units/999999/descendants")
    assert response.status_code == 404


async def test_update_rejects_circular_parent(db_client: AsyncClient, db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    child = await make_org_unit(db_session, name="CenterWell", parent_id=root.id)

    response = await db_client.patch(
        f"/api/v1/org-units/{root.id}",
        json={"parent_id": child.id},
    )
    assert response.status_code == 409


async def test_reparent_to_parentless_returns_409(db_client: AsyncClient, db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    child = await make_org_unit(db_session, name="CenterWell", parent_id=root.id)
    response = await db_client.patch(f"/api/v1/org-units/{child.id}", json={"parent_id": None})
    assert_error(response, 409, "duplicate_root", message_contains="top-level")


async def test_reparent_losing_a_concurrent_rollup_returns_retryable_409(
    db_client: AsyncClient, db_session: AsyncSession, mocker
) -> None:
    root = await make_org_unit(db_session, name="Humana")
    child = await make_org_unit(db_session, name="CenterWell", parent_id=root.id)
    grandchild = await make_org_unit(db_session, name="Primary Care", parent_id=child.id)

    mocker.patch.object(
        score_snapshot_service,
        "_acquire_rollup_lock",
        side_effect=ConcurrentRollupError("Org unit", child.id),
    )

    response = await db_client.patch(f"/api/v1/org-units/{grandchild.id}", json={"parent_id": root.id})
    assert_error(response, 409, "concurrent_rollup", message_contains="retry")


async def test_delete_org_unit_with_apps(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session, name="Humana")
    brand = await make_brand(db_session)
    await make_app(db_session, name="MyHumana", slug="myhumana", brand_id=brand.id, org_unit_id=org_unit.id)

    response = await db_client.delete(f"/api/v1/org-units/{org_unit.id}")
    assert_error(response, 409, "has_dependents", message_contains="dependent")
