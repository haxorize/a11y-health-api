"""Every listing forwards the client's page size to its service.

A handler that drops `limit=pagination.limit` type-checks clean and serves
the service default, so `?limit=1` is ignored with nothing else red. The
paging mechanics are proven in tests/core/test_pagination.py; this pins only
the forwarding, on each listing no router file already sends a `limit` to.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import (
    make_app_with_org_unit,
    make_brand,
    make_org_unit,
    make_page_result,
    make_scan_run_with_parents,
    make_score_snapshot,
)

type Listing = tuple[str, dict[str, str]]

_FIRST = datetime(2026, 4, 1, tzinfo=UTC)
_SECOND = datetime(2026, 4, 2, tzinfo=UTC)


async def _two_apps(db: AsyncSession) -> Listing:
    await make_app_with_org_unit(db, org_name="Org A", app_name="App A", slug="app-a")
    await make_app_with_org_unit(db, org_name="Org B", app_name="App B", slug="app-b")
    return "/api/v1/apps", {}


async def _two_app_scores(db: AsyncSession) -> Listing:
    app = await make_app_with_org_unit(db)
    await make_score_snapshot(db, app_id=app.id, snapshot_at=_FIRST)
    await make_score_snapshot(db, app_id=app.id, snapshot_at=_SECOND)
    return f"/api/v1/apps/{app.id}/scores", {}


async def _two_org_unit_scores(db: AsyncSession) -> Listing:
    org_unit = await make_org_unit(db)
    await make_score_snapshot(db, org_unit_id=org_unit.id, snapshot_at=_FIRST)
    await make_score_snapshot(db, org_unit_id=org_unit.id, snapshot_at=_SECOND)
    return f"/api/v1/org-units/{org_unit.id}/scores", {}


async def _two_brand_scores(db: AsyncSession) -> Listing:
    brand = await make_brand(db)
    await make_score_snapshot(db, brand_id=brand.id, snapshot_at=_FIRST)
    await make_score_snapshot(db, brand_id=brand.id, snapshot_at=_SECOND)
    return f"/api/v1/brands/{brand.id}/scores", {}


async def _two_latest_scores(db: AsyncSession) -> Listing:
    app_a = await make_app_with_org_unit(db, org_name="Org A", app_name="App A", slug="app-a")
    app_b = await make_app_with_org_unit(db, org_name="Org B", app_name="App B", slug="app-b")
    await make_score_snapshot(db, app_id=app_a.id)
    await make_score_snapshot(db, app_id=app_b.id)
    return "/api/v1/scores/latest", {"owner_type": "app"}


async def _two_scan_run_pages(db: AsyncSession) -> Listing:
    scan_run = await make_scan_run_with_parents(db)
    await make_page_result(db, scan_run_id=scan_run.id, url="https://example.com/a")
    await make_page_result(db, scan_run_id=scan_run.id, url="https://example.com/b")
    return f"/api/v1/scan-runs/{scan_run.id}/pages", {}


@pytest.mark.parametrize(
    "arrange",
    [
        _two_apps,
        _two_app_scores,
        _two_org_unit_scores,
        _two_brand_scores,
        _two_latest_scores,
        _two_scan_run_pages,
    ],
)
async def test_listing_forwards_limit(
    db_client: AsyncClient,
    db_session: AsyncSession,
    arrange: Callable[[AsyncSession], Awaitable[Listing]],
) -> None:
    path, params = await arrange(db_session)

    response = await db_client.get(path, params={**params, "limit": 1})

    assert response.status_code == 200
    page = response.json()
    assert len(page["items"]) == 1
    assert page["next_cursor"] is not None
