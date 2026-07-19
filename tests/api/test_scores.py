from datetime import UTC, datetime

from httpx import AsyncClient
from pytest import approx
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_app_with_org_unit, make_brand, make_org_unit, make_score_snapshot


async def test_list_app_scores_ordered_chronologically(db_client: AsyncClient, db_session: AsyncSession) -> None:
    app = await make_app_with_org_unit(db_session)

    await make_score_snapshot(db_session, app_id=app.id, score=0.6, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC))
    await make_score_snapshot(db_session, app_id=app.id, score=0.9, snapshot_at=datetime(2026, 4, 1, tzinfo=UTC))
    await make_score_snapshot(db_session, app_id=app.id, score=0.75, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC))

    response = await db_client.get(f"/api/v1/apps/{app.id}/scores")
    assert response.status_code == 200

    items = response.json()["items"]
    assert len(items) == 3
    scores = [s["score"] for s in items]
    assert scores == approx([0.9, 0.75, 0.6])
    assert "avg_violations_per_page" not in items[0]
    assert "pct_pages_with_violations" not in items[0]
    assert "pct_pages_with_critical_violations" not in items[0]


async def test_list_org_unit_scores_ordered_chronologically(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)

    await make_score_snapshot(
        db_session, org_unit_id=org_unit.id, score=0.5, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )
    await make_score_snapshot(
        db_session, org_unit_id=org_unit.id, score=0.7, snapshot_at=datetime(2026, 4, 1, tzinfo=UTC)
    )
    await make_score_snapshot(
        db_session, org_unit_id=org_unit.id, score=0.6, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )

    response = await db_client.get(f"/api/v1/org-units/{org_unit.id}/scores")
    assert response.status_code == 200

    items = response.json()["items"]
    assert len(items) == 3
    scores = [s["score"] for s in items]
    assert scores == approx([0.7, 0.6, 0.5])


async def test_list_app_scores_desc_orders_newest_first(db_client: AsyncClient, db_session: AsyncSession) -> None:
    app = await make_app_with_org_unit(db_session)

    await make_score_snapshot(db_session, app_id=app.id, score=0.6, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC))
    await make_score_snapshot(db_session, app_id=app.id, score=0.9, snapshot_at=datetime(2026, 4, 1, tzinfo=UTC))
    await make_score_snapshot(db_session, app_id=app.id, score=0.75, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC))

    response = await db_client.get(f"/api/v1/apps/{app.id}/scores", params={"order": "desc"})
    assert response.status_code == 200

    scores = [s["score"] for s in response.json()["items"]]
    assert scores == approx([0.6, 0.75, 0.9])


async def test_list_org_unit_scores_desc_orders_newest_first(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)

    await make_score_snapshot(
        db_session, org_unit_id=org_unit.id, score=0.5, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )
    await make_score_snapshot(
        db_session, org_unit_id=org_unit.id, score=0.7, snapshot_at=datetime(2026, 4, 1, tzinfo=UTC)
    )

    response = await db_client.get(f"/api/v1/org-units/{org_unit.id}/scores", params={"order": "desc"})
    assert response.status_code == 200

    scores = [s["score"] for s in response.json()["items"]]
    assert scores == approx([0.5, 0.7])


async def test_list_app_scores_empty(db_client: AsyncClient, db_session: AsyncSession) -> None:
    app = await make_app_with_org_unit(db_session)

    response = await db_client.get(f"/api/v1/apps/{app.id}/scores")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []


async def test_list_org_unit_scores_empty(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)

    response = await db_client.get(f"/api/v1/org-units/{org_unit.id}/scores")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []


async def test_list_app_scores_not_found(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/apps/999999/scores")
    assert response.status_code == 404


async def test_list_org_unit_scores_not_found(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/org-units/999999/scores")
    assert response.status_code == 404


async def test_list_brand_scores_ordered_chronologically(db_client: AsyncClient, db_session: AsyncSession) -> None:
    brand = await make_brand(db_session)

    await make_score_snapshot(db_session, brand_id=brand.id, score=0.5, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC))
    await make_score_snapshot(db_session, brand_id=brand.id, score=0.7, snapshot_at=datetime(2026, 4, 1, tzinfo=UTC))
    await make_score_snapshot(db_session, brand_id=brand.id, score=0.6, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC))

    response = await db_client.get(f"/api/v1/brands/{brand.id}/scores")
    assert response.status_code == 200

    items = response.json()["items"]
    assert len(items) == 3
    scores = [s["score"] for s in items]
    assert scores == approx([0.7, 0.6, 0.5])


async def test_list_brand_scores_desc_orders_newest_first(db_client: AsyncClient, db_session: AsyncSession) -> None:
    brand = await make_brand(db_session)

    await make_score_snapshot(db_session, brand_id=brand.id, score=0.5, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC))
    await make_score_snapshot(db_session, brand_id=brand.id, score=0.7, snapshot_at=datetime(2026, 4, 1, tzinfo=UTC))

    response = await db_client.get(f"/api/v1/brands/{brand.id}/scores", params={"order": "desc"})
    assert response.status_code == 200

    scores = [s["score"] for s in response.json()["items"]]
    assert scores == approx([0.5, 0.7])


async def test_list_brand_scores_empty(db_client: AsyncClient, db_session: AsyncSession) -> None:
    brand = await make_brand(db_session)

    response = await db_client.get(f"/api/v1/brands/{brand.id}/scores")
    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []


async def test_list_brand_scores_not_found(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/brands/999999/scores")
    assert response.status_code == 404


async def test_list_app_scores_invalid_order(db_client: AsyncClient, db_session: AsyncSession) -> None:
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
