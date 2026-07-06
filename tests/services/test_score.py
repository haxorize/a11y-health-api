from datetime import UTC, datetime

from pytest import approx
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.enums import ScoreSnapshotOwnerType
from a11y_health.services import score as score_service
from a11y_health.services import score_snapshot as score_snapshot_service
from tests.factories import (
    latest_brand_snapshot,
    make_app_with_org_unit,
    make_brand,
    make_score_snapshot,
)


async def test_list_latest_scores_returns_one_latest_snapshot_per_app(db_session: AsyncSession) -> None:
    app_a = await make_app_with_org_unit(db_session, org_name="Org A", app_name="App A", slug="app-a")
    app_b = await make_app_with_org_unit(db_session, org_name="Org B", app_name="App B", slug="app-b")
    # no snapshots — must be absent from the result, not null-filled
    await make_app_with_org_unit(db_session, org_name="Org C", app_name="App C", slug="app-c")

    await make_score_snapshot(db_session, app_id=app_a.id, score=0.5, snapshot_at=datetime(2026, 4, 1, tzinfo=UTC))
    latest_a = await make_score_snapshot(
        db_session, app_id=app_a.id, score=0.9, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )
    latest_b = await make_score_snapshot(
        db_session, app_id=app_b.id, score=0.7, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )

    page = await score_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.APP)

    assert {(s.app_id, s.id) for s in page.items} == {(app_a.id, latest_a.id), (app_b.id, latest_b.id)}
    assert page.next_cursor is None


async def test_latest_selection_matches_rollup_after_out_of_order_import(db_session: AsyncSession) -> None:
    brand = await make_brand(db_session)
    app_a = await make_app_with_org_unit(db_session, org_name="Org A", slug="app-a", brand_id=brand.id)
    app_b = await make_app_with_org_unit(db_session, org_name="Org B", slug="app-b", brand_id=brand.id)

    # App A: newest observation ingested first; a historical backfill arrives later
    # (higher id, older snapshot_at) and must not displace it
    latest_a = await make_score_snapshot(
        db_session, app_id=app_a.id, score=0.9, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )
    await make_score_snapshot(db_session, app_id=app_a.id, score=0.2, snapshot_at=datetime(2026, 3, 1, tzinfo=UTC))

    # App B: identical snapshot_at — the higher id wins
    await make_score_snapshot(db_session, app_id=app_b.id, score=0.4, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC))
    latest_b = await make_score_snapshot(
        db_session, app_id=app_b.id, score=0.6, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )

    page = await score_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.APP)
    assert {(s.app_id, s.id) for s in page.items} == {(app_a.id, latest_a.id), (app_b.id, latest_b.id)}

    # Parity: the Brand Rollup aggregates exactly the snapshots served above —
    # its score is the mean of theirs (0.9 and 0.6), not of the backfill/tie losers
    await score_snapshot_service.rollup_brand_scores(db_session, brand.id)
    brand_snapshot = await latest_brand_snapshot(db_session, brand.id)
    assert brand_snapshot.score == approx((0.9 + 0.6) / 2)


async def test_served_owner_not_repeated_when_import_lands_mid_walk(db_session: AsyncSession) -> None:
    app_a = await make_app_with_org_unit(db_session, org_name="Org A", app_name="App A", slug="app-a")
    app_b = await make_app_with_org_unit(db_session, org_name="Org B", app_name="App B", slug="app-b")
    await make_score_snapshot(db_session, app_id=app_a.id, score=0.5, snapshot_at=datetime(2026, 4, 1, tzinfo=UTC))
    latest_b = await make_score_snapshot(
        db_session, app_id=app_b.id, score=0.7, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )

    first = await score_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.APP, limit=1)
    assert [s.app_id for s in first.items] == [app_a.id]

    # a scan for the already-served app completes before the next page is fetched
    await make_score_snapshot(db_session, app_id=app_a.id, score=0.9, snapshot_at=datetime(2026, 4, 5, tzinfo=UTC))

    second = await score_service.list_latest_scores(
        db_session, ScoreSnapshotOwnerType.APP, cursor=first.next_cursor, limit=1
    )
    assert [(s.app_id, s.id) for s in second.items] == [(app_b.id, latest_b.id)]
    assert second.next_cursor is None


async def test_list_latest_scores_filters_by_owner_type(db_session: AsyncSession) -> None:
    brand = await make_brand(db_session)
    app = await make_app_with_org_unit(db_session, org_name="Org A", slug="app-a", brand_id=brand.id)

    app_snapshot = await make_score_snapshot(
        db_session, app_id=app.id, score=0.9, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )
    org_unit_snapshot = await make_score_snapshot(
        db_session, org_unit_id=app.org_unit_id, score=0.8, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )
    brand_snapshot = await make_score_snapshot(
        db_session, brand_id=brand.id, score=0.7, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )

    for owner_type, expected in [
        (ScoreSnapshotOwnerType.APP, app_snapshot),
        (ScoreSnapshotOwnerType.ORG_UNIT, org_unit_snapshot),
        (ScoreSnapshotOwnerType.BRAND, brand_snapshot),
    ]:
        page = await score_service.list_latest_scores(db_session, owner_type)
        assert [s.id for s in page.items] == [expected.id]
