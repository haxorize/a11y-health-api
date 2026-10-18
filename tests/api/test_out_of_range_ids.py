from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import IDENTITY_CEILING, assert_error, make_org_unit

Send = Callable[[AsyncClient, AsyncSession, int], Awaitable[Response]]


async def _get_app(client: AsyncClient, db: AsyncSession, id_: int) -> Response:
    return await client.get(f"/api/v1/apps/{id_}")


async def _create_app_with_brand(client: AsyncClient, db: AsyncSession, id_: int) -> Response:
    org_unit = await make_org_unit(db)
    return await client.post("/api/v1/apps", json={"name": "MyHumana", "brand_id": id_, "org_unit_id": org_unit.id})


async def _latest_scores_for_brand(client: AsyncClient, db: AsyncSession, id_: int) -> Response:
    return await client.get("/api/v1/scores/latest", params={"owner_type": "app", "brand_id": id_})


# One site per kind of id input: a path parameter, a request body field, and
# a query filter. tests/test_id_bounds.py holds every site to the bound in the
# spec.
_SITES = [
    pytest.param(_get_app, ["path", "app_id"], id="path"),
    pytest.param(_create_app_with_brand, ["body", "brand_id"], id="body"),
    pytest.param(_latest_scores_for_brand, ["query", "brand_id"], id="query"),
]
_SENDS = [pytest.param(site.values[0], id=site.id) for site in _SITES]


@pytest.mark.parametrize(("send", "loc"), _SITES)
@pytest.mark.parametrize("id_", [0, -1, IDENTITY_CEILING + 1])
async def test_an_id_outside_the_identity_range_is_refused(
    db_client: AsyncClient, db_session: AsyncSession, send: Send, loc: list[str], id_: int
) -> None:
    response = await send(db_client, db_session, id_)

    assert response.status_code == 422
    assert [error["loc"] for error in response.json()["detail"]] == [loc]


@pytest.mark.parametrize("send", _SENDS)
@pytest.mark.parametrize("id_", [1, IDENTITY_CEILING])
async def test_an_id_inside_the_identity_range_reaches_the_lookup(
    db_client: AsyncClient, db_session: AsyncSession, send: Send, id_: int
) -> None:
    response = await send(db_client, db_session, id_)

    assert_error(response, 404, "not_found")
