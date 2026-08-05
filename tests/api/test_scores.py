from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from pytest import approx
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_app, make_app_with_org_unit, make_brand, make_org_unit, make_score_snapshot

_OWNERS = ["app", "org_unit", "brand"]


async def _owner_scores_path(db: AsyncSession, owner: str) -> tuple[str, dict[str, int]]:
    """One owner of the given kind: its /scores path and the make_score_snapshot
    kwarg addressing it."""
    match owner:
        case "app":
            app = await make_app_with_org_unit(db)
            return f"/api/v1/apps/{app.id}/scores", {"app_id": app.id}
        case "org_unit":
            org_unit = await make_org_unit(db)
            return f"/api/v1/org-units/{org_unit.id}/scores", {"org_unit_id": org_unit.id}
        case "brand":
            brand = await make_brand(db)
            return f"/api/v1/brands/{brand.id}/scores", {"brand_id": brand.id}
    raise AssertionError(owner)


@pytest.mark.parametrize("owner", _OWNERS)
async def test_list_scores_ordered_chronologically(
    db_client: AsyncClient, db_session: AsyncSession, owner: str
) -> None:
    path, owner_kw = await _owner_scores_path(db_session, owner)

    await make_score_snapshot(db_session, **owner_kw, score=0.6, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC))
    await make_score_snapshot(db_session, **owner_kw, score=0.9, snapshot_at=datetime(2026, 4, 1, tzinfo=UTC))
    await make_score_snapshot(db_session, **owner_kw, score=0.75, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC))

    response = await db_client.get(path)
    assert response.status_code == 200

    items = response.json()["items"]
    assert len(items) == 3
    scores = [s["score"] for s in items]
    assert scores == approx([0.9, 0.75, 0.6])
    # Raw counts only on the wire — no derived shares or averages (ADR 0027).
    assert "avg_violations_per_page" not in items[0]
    assert "pct_pages_with_violations" not in items[0]
    assert "pct_pages_with_critical_violations" not in items[0]


@pytest.mark.parametrize("owner", _OWNERS)
async def test_list_scores_desc_orders_newest_first(
    db_client: AsyncClient, db_session: AsyncSession, owner: str
) -> None:
    path, owner_kw = await _owner_scores_path(db_session, owner)

    await make_score_snapshot(db_session, **owner_kw, score=0.6, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC))
    await make_score_snapshot(db_session, **owner_kw, score=0.9, snapshot_at=datetime(2026, 4, 1, tzinfo=UTC))
    await make_score_snapshot(db_session, **owner_kw, score=0.75, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC))

    response = await db_client.get(path, params={"order": "desc"})
    assert response.status_code == 200

    scores = [s["score"] for s in response.json()["items"]]
    assert scores == approx([0.6, 0.75, 0.9])


@pytest.mark.parametrize("owner", _OWNERS)
async def test_list_scores_empty(db_client: AsyncClient, db_session: AsyncSession, owner: str) -> None:
    path, _ = await _owner_scores_path(db_session, owner)

    response = await db_client.get(path)
    assert response.status_code == 200
    assert response.json()["items"] == []


@pytest.mark.parametrize("route", ["apps", "org-units", "brands"])
async def test_list_scores_not_found(db_client: AsyncClient, route: str) -> None:
    response = await db_client.get(f"/api/v1/{route}/999999/scores")
    assert response.status_code == 404


async def test_list_scores_invalid_order(db_client: AsyncClient, db_session: AsyncSession) -> None:
    app = await make_app_with_org_unit(db_session)

    response = await db_client.get(f"/api/v1/apps/{app.id}/scores", params={"order": "sideways"})
    assert response.status_code == 422


async def test_list_latest_scores_round_trip(db_client: AsyncClient, db_session: AsyncSession) -> None:
    app_a = await make_app_with_org_unit(db_session, org_name="Org A", app_name="App A", slug="app-a")
    app_b = await make_app_with_org_unit(db_session, org_name="Org B", app_name="App B", slug="app-b")
    # never scanned — absent from the response, not null-filled
    await make_app_with_org_unit(db_session, org_name="Org C", app_name="App C", slug="app-c")

    await make_score_snapshot(db_session, app_id=app_a.id, score=0.5, snapshot_at=datetime(2026, 4, 1, tzinfo=UTC))
    latest_a = await make_score_snapshot(
        db_session, app_id=app_a.id, score=0.8, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )
    latest_b = await make_score_snapshot(
        db_session, app_id=app_b.id, score=0.6, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )

    response = await db_client.get("/api/v1/scores/latest", params={"owner_type": "app"})
    assert response.status_code == 200

    page = response.json()
    assert {item["id"] for item in page["items"]} == {latest_a.id, latest_b.id}
    assert page["next_cursor"] is None


async def test_list_latest_scores_owner_id_params_decode_to_filter(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    app_a = await make_app_with_org_unit(db_session, org_name="Org A", app_name="App A", slug="app-a")
    app_b = await make_app_with_org_unit(db_session, org_name="Org B", app_name="App B", slug="app-b")
    excluded = await make_app_with_org_unit(db_session, org_name="Org C", app_name="App C", slug="app-c")

    latest_a = await make_score_snapshot(
        db_session, app_id=app_a.id, score=0.8, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )
    latest_b = await make_score_snapshot(
        db_session, app_id=app_b.id, score=0.6, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )
    await make_score_snapshot(db_session, app_id=excluded.id, score=0.4, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC))

    response = await db_client.get(
        "/api/v1/scores/latest", params={"owner_type": "app", "owner_id": [app_a.id, app_b.id]}
    )
    assert response.status_code == 200

    page = response.json()
    assert {item["id"] for item in page["items"]} == {latest_a.id, latest_b.id}


async def test_list_latest_scores_invalid_owner_type(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/scores/latest", params={"owner_type": "fleet"})
    assert response.status_code == 422


async def test_list_latest_scores_under_org_unit_id_param_decodes_to_subtree_scope(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    root = await make_org_unit(db_session, name="Root")
    scoped = await make_org_unit(db_session, name="Scoped", parent_id=root.id)
    sibling = await make_org_unit(db_session, name="Sibling", parent_id=root.id)
    inside = await make_app(db_session, name="Inside", slug="inside", org_unit_id=scoped.id)
    outside = await make_app(db_session, name="Outside", slug="outside", org_unit_id=sibling.id)

    kept = await make_score_snapshot(
        db_session, app_id=inside.id, score=0.9, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )
    await make_score_snapshot(db_session, app_id=outside.id, score=0.5, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC))

    response = await db_client.get(
        "/api/v1/scores/latest", params={"owner_type": "app", "under_org_unit_id": scoped.id}
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [kept.id]


async def test_list_latest_scores_unknown_under_org_unit_id_is_404(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/scores/latest", params={"owner_type": "app", "under_org_unit_id": 999999})
    assert response.status_code == 404


async def test_list_latest_scores_direct_only_param_decodes_to_direct_scope(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    root = await make_org_unit(db_session, name="Root")
    scoped = await make_org_unit(db_session, name="Scoped", parent_id=root.id)
    child = await make_org_unit(db_session, name="Child", parent_id=scoped.id)
    own = await make_app(db_session, name="Own", slug="own", org_unit_id=scoped.id)
    deep = await make_app(db_session, name="Deep", slug="deep", org_unit_id=child.id)

    kept = await make_score_snapshot(db_session, app_id=own.id, score=0.9, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC))
    await make_score_snapshot(db_session, app_id=deep.id, score=0.5, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC))

    response = await db_client.get(
        "/api/v1/scores/latest",
        params={"owner_type": "app", "under_org_unit_id": scoped.id, "direct_only": "true"},
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [kept.id]


async def test_list_latest_scores_brand_id_param_decodes_to_brand_scope(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    brand = await make_brand(db_session)
    other = await make_brand(db_session)
    root = await make_org_unit(db_session, name="Root")
    inside = await make_app(db_session, name="Inside", slug="inside", brand_id=brand.id, org_unit_id=root.id)
    outside = await make_app(db_session, name="Outside", slug="outside", brand_id=other.id, org_unit_id=root.id)

    kept = await make_score_snapshot(
        db_session, app_id=inside.id, score=0.9, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )
    await make_score_snapshot(db_session, app_id=outside.id, score=0.5, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC))

    response = await db_client.get("/api/v1/scores/latest", params={"owner_type": "app", "brand_id": brand.id})

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["items"]] == [kept.id]


async def test_list_latest_scores_unknown_brand_id_is_404(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/scores/latest", params={"owner_type": "app", "brand_id": 999999})
    assert response.status_code == 404
