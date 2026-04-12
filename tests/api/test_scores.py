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

    data = response.json()
    assert len(data) == 3
    scores = [s["score"] for s in data]
    assert scores == approx([0.9, 0.75, 0.6])


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

    data = response.json()
    assert len(data) == 3
    scores = [s["score"] for s in data]
    assert scores == approx([0.7, 0.6, 0.5])


async def test_list_app_scores_empty(db_client: AsyncClient, db_session: AsyncSession) -> None:
    app = await make_app_with_org_unit(db_session)

    response = await db_client.get(f"/api/v1/apps/{app.id}/scores")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_org_unit_scores_empty(db_client: AsyncClient, db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)

    response = await db_client.get(f"/api/v1/org-units/{org_unit.id}/scores")
    assert response.status_code == 200
    assert response.json() == []


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

    data = response.json()
    assert len(data) == 3
    scores = [s["score"] for s in data]
    assert scores == approx([0.7, 0.6, 0.5])


async def test_list_brand_scores_empty(db_client: AsyncClient, db_session: AsyncSession) -> None:
    brand = await make_brand(db_session)

    response = await db_client.get(f"/api/v1/brands/{brand.id}/scores")
    assert response.status_code == 200
    assert response.json() == []


async def test_list_brand_scores_not_found(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/brands/999999/scores")
    assert response.status_code == 404
