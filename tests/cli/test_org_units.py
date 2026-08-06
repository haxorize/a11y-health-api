import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.cli._client import ApiError, create_org_unit, list_org_units
from tests.factories import make_org_unit


async def test_list_org_units_returns_id_name_and_parent(db_session: AsyncSession, db_client: AsyncClient) -> None:
    parent = await make_org_unit(db_session, name="Humana")
    await make_org_unit(db_session, name="CenterWell", parent_id=parent.id)

    rows = await list_org_units(db_client)

    by_name = {row["name"]: row for row in rows}
    assert by_name["Humana"]["id"] == parent.id
    assert by_name["Humana"]["parent_id"] is None
    assert by_name["CenterWell"]["parent_id"] == parent.id


async def test_create_org_unit_returns_created_id(db_client: AsyncClient) -> None:
    org_unit_id = await create_org_unit(db_client, name="Engineering")

    assert isinstance(org_unit_id, int)
    resp = await db_client.get(f"/api/v1/org-units/{org_unit_id}")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Engineering"
    assert resp.json()["parent_id"] is None


async def test_create_org_unit_nests_under_parent(db_session: AsyncSession, db_client: AsyncClient) -> None:
    parent = await make_org_unit(db_session, name="Humana")

    org_unit_id = await create_org_unit(db_client, name="CenterWell", parent_id=parent.id)

    resp = await db_client.get(f"/api/v1/org-units/{org_unit_id}")
    assert resp.json()["parent_id"] == parent.id


async def test_create_org_unit_unknown_parent_surfaces_coded_error(db_client: AsyncClient) -> None:
    with pytest.raises(ApiError) as exc_info:
        await create_org_unit(db_client, name="Orphan", parent_id=999999)

    # "not_found" is the API's declared Error Code for the unknown-parent mode, not a recomputation.
    assert exc_info.value.code == "not_found"
    assert exc_info.value.message


async def test_list_org_units_surfaces_coded_error_on_failure() -> None:
    # A non-2xx from the list endpoint must raise the coded ApiError every other CLI
    # call raises (so main() prints a clean ERROR line), not a raw HTTPStatusError.
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"code": "service_unavailable", "message": "db down"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test") as client:
        with pytest.raises(ApiError) as exc_info:
            await list_org_units(client)

    assert exc_info.value.code == "service_unavailable"
    assert exc_info.value.message == "db down"
