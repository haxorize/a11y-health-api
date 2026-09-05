from datetime import UTC, datetime

from pytest import approx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.score_snapshot import ScoreSnapshot
from a11y_health.services.scoring_orchestration import (
    on_app_latest_snapshot_changed,
    on_app_reassigned,
    on_org_unit_reparented,
    on_scan_run_completed,
)
from tests.factories import (
    ingest_pages_and_complete,
    latest_brand_snapshot,
    latest_ou_snapshot,
    make_app,
    make_axe_payload,
    make_brand,
    make_org_unit,
    make_scan_run,
    make_score_snapshot,
    make_violation,
)


class TestOnScanRunCompleted:
    async def test_creates_app_and_rollup_snapshots(self, db_session: AsyncSession) -> None:
        root = await make_org_unit(db_session, name="Root")
        middle = await make_org_unit(db_session, name="Middle", parent_id=root.id)
        leaf = await make_org_unit(db_session, name="Leaf", parent_id=middle.id)
        app = await make_app(db_session, name="App", slug="app-1", org_unit_id=leaf.id)
        scan_run = await make_scan_run(db_session, app_id=app.id)

        payload = make_axe_payload(violations=[make_violation("r1", "serious")])
        scan_run = await ingest_pages_and_complete(db_session, scan_run.id, [payload])
        await on_scan_run_completed(db_session, scan_run)

        app_snap = await db_session.execute(select(ScoreSnapshot).where(ScoreSnapshot.app_id == app.id))
        app_snapshot = app_snap.scalar_one()
        assert app_snapshot.score == approx(0.4)
        assert app_snapshot.total_pages == 1

        for ou in [leaf, middle, root]:
            snapshot = await latest_ou_snapshot(db_session, ou.id)
            assert snapshot.score == approx(0.4)

    async def test_rolls_up_brand(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="Humana")
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(db_session, name="App", slug="app-brand", org_unit_id=org_unit.id, brand_id=brand.id)
        scan_run = await make_scan_run(db_session, app_id=app.id)

        payload = make_axe_payload(violations=[make_violation("r1", "serious")])
        scan_run = await ingest_pages_and_complete(db_session, scan_run.id, [payload])
        await on_scan_run_completed(db_session, scan_run)

        brand_snap = await latest_brand_snapshot(db_session, brand.id)
        assert brand_snap.score == approx(0.4)
        assert brand_snap.total_pages == 1

    async def test_backfill_rollup_uses_newest_child_observation_time(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="Humana")
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(db_session, name="App", slug="app-backfill", org_unit_id=org_unit.id, brand_id=brand.id)

        sr_new = await make_scan_run(db_session, app_id=app.id, scanned_at=datetime(2026, 4, 1, tzinfo=UTC))
        sr_new = await ingest_pages_and_complete(
            db_session, sr_new.id, [make_axe_payload(url="https://example.com/new")]
        )
        await on_scan_run_completed(db_session, sr_new)

        sr_old = await make_scan_run(db_session, app_id=app.id, scanned_at=datetime(2023, 5, 1, tzinfo=UTC))
        sr_old = await ingest_pages_and_complete(
            db_session, sr_old.id, [make_axe_payload(url="https://example.com/old")]
        )
        await on_scan_run_completed(db_session, sr_old)

        ou_snap = await latest_ou_snapshot(db_session, org_unit.id)
        assert ou_snap.snapshot_at == datetime(2026, 4, 1, tzinfo=UTC)
        brand_snap = await latest_brand_snapshot(db_session, brand.id)
        assert brand_snap.snapshot_at == datetime(2026, 4, 1, tzinfo=UTC)

    async def test_multi_app_brand(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="CenterWell")
        org_unit = await make_org_unit(db_session, name="Org")
        app_a = await make_app(db_session, name="App A", slug="app-a", org_unit_id=org_unit.id, brand_id=brand.id)
        app_b = await make_app(db_session, name="App B", slug="app-b", org_unit_id=org_unit.id, brand_id=brand.id)

        payload_a = make_axe_payload(violations=[make_violation("r1", "serious")])
        sr_a = await make_scan_run(db_session, app_id=app_a.id)
        sr_a = await ingest_pages_and_complete(db_session, sr_a.id, [payload_a])
        await on_scan_run_completed(db_session, sr_a)

        payload_b = make_axe_payload(url="https://example.com/b")
        sr_b = await make_scan_run(db_session, app_id=app_b.id)
        sr_b = await ingest_pages_and_complete(db_session, sr_b.id, [payload_b])
        await on_scan_run_completed(db_session, sr_b)

        brand_snap = await latest_brand_snapshot(db_session, brand.id)
        assert brand_snap.score == approx(0.7)
        assert brand_snap.total_pages == 2


class TestOnScanRunDeleted:
    async def test_app_snapshot_reflects_remaining_run(self, db_session: AsyncSession) -> None:
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(db_session, name="App", slug="app-recomp", org_unit_id=org_unit.id)

        sr_a = await make_scan_run(db_session, app_id=app.id, scanned_at=datetime(2026, 3, 1, tzinfo=UTC))
        payload_a = make_axe_payload(violations=[make_violation("r1", "serious")])
        sr_a = await ingest_pages_and_complete(db_session, sr_a.id, [payload_a])
        await on_scan_run_completed(db_session, sr_a)

        sr_b = await make_scan_run(db_session, app_id=app.id, scanned_at=datetime(2026, 4, 1, tzinfo=UTC))
        payload_b = make_axe_payload(url="https://example.com/b")
        sr_b = await ingest_pages_and_complete(db_session, sr_b.id, [payload_b])
        await on_scan_run_completed(db_session, sr_b)

        await db_session.delete(sr_b)
        await db_session.flush()
        await on_app_latest_snapshot_changed(db_session, org_unit.id, app.brand_id)

        result = await db_session.execute(select(ScoreSnapshot).where(ScoreSnapshot.app_id == app.id))
        app_snapshots = result.scalars().all()
        assert len(app_snapshots) == 1
        assert app_snapshots[0].scan_run_id == sr_a.id
        assert app_snapshots[0].score == approx(0.4)

    async def test_recalculates_org_unit_rollups(self, db_session: AsyncSession) -> None:
        root = await make_org_unit(db_session, name="Root")
        leaf = await make_org_unit(db_session, name="Leaf", parent_id=root.id)
        app = await make_app(db_session, name="App", slug="app-del-sr", org_unit_id=leaf.id)

        sr_a = await make_scan_run(db_session, app_id=app.id, scanned_at=datetime(2026, 3, 1, tzinfo=UTC))
        payload_a = make_axe_payload(violations=[make_violation("r1", "serious")])
        sr_a = await ingest_pages_and_complete(db_session, sr_a.id, [payload_a])
        await on_scan_run_completed(db_session, sr_a)

        sr_b = await make_scan_run(db_session, app_id=app.id, scanned_at=datetime(2026, 4, 1, tzinfo=UTC))
        payload_b = make_axe_payload(url="https://example.com/b")
        sr_b = await ingest_pages_and_complete(db_session, sr_b.id, [payload_b])
        await on_scan_run_completed(db_session, sr_b)

        leaf_before = await latest_ou_snapshot(db_session, leaf.id)
        assert leaf_before.score == approx(1.0)

        await db_session.delete(sr_b)
        await db_session.flush()
        await on_app_latest_snapshot_changed(db_session, leaf.id, app.brand_id)

        leaf_after = await latest_ou_snapshot(db_session, leaf.id)
        assert leaf_after.score == approx(0.4)
        root_after = await latest_ou_snapshot(db_session, root.id)
        assert root_after.score == approx(0.4)

    async def test_recalculates_brand_rollups(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="CenterWell")
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(
            db_session, name="App", slug="app-del-sr-brand", org_unit_id=org_unit.id, brand_id=brand.id
        )

        sr_a = await make_scan_run(db_session, app_id=app.id, scanned_at=datetime(2026, 3, 1, tzinfo=UTC))
        payload_a = make_axe_payload(violations=[make_violation("r1", "serious")])
        sr_a = await ingest_pages_and_complete(db_session, sr_a.id, [payload_a])
        await on_scan_run_completed(db_session, sr_a)

        sr_b = await make_scan_run(db_session, app_id=app.id, scanned_at=datetime(2026, 4, 1, tzinfo=UTC))
        payload_b = make_axe_payload(url="https://example.com/b")
        sr_b = await ingest_pages_and_complete(db_session, sr_b.id, [payload_b])
        await on_scan_run_completed(db_session, sr_b)

        brand_before = await latest_brand_snapshot(db_session, brand.id)
        assert brand_before.score == approx(1.0)

        await db_session.delete(sr_b)
        await db_session.flush()
        await on_app_latest_snapshot_changed(db_session, org_unit.id, brand.id)

        brand_after = await latest_brand_snapshot(db_session, brand.id)
        assert brand_after.score == approx(0.4)

    async def test_delete_older_scan_stamps_rollup_with_remaining_observation(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="Humana")
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(db_session, name="App", slug="app-del-older", org_unit_id=org_unit.id, brand_id=brand.id)

        sr_old = await make_scan_run(db_session, app_id=app.id, scanned_at=datetime(2023, 5, 1, tzinfo=UTC))
        sr_old = await ingest_pages_and_complete(
            db_session, sr_old.id, [make_axe_payload(url="https://example.com/old")]
        )
        await on_scan_run_completed(db_session, sr_old)
        sr_new = await make_scan_run(db_session, app_id=app.id, scanned_at=datetime(2023, 6, 1, tzinfo=UTC))
        sr_new = await ingest_pages_and_complete(
            db_session, sr_new.id, [make_axe_payload(url="https://example.com/new")]
        )
        await on_scan_run_completed(db_session, sr_new)

        await db_session.delete(sr_old)
        await db_session.flush()
        await on_app_latest_snapshot_changed(db_session, org_unit.id, brand.id)

        ou_snap = await latest_ou_snapshot(db_session, org_unit.id)
        assert ou_snap.snapshot_at == datetime(2023, 6, 1, tzinfo=UTC)
        brand_snap = await latest_brand_snapshot(db_session, brand.id)
        assert brand_snap.snapshot_at == datetime(2023, 6, 1, tzinfo=UTC)

    async def test_delete_prunes_forward_stale_rollups(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="Humana")
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(db_session, name="App", slug="app-prune", org_unit_id=org_unit.id, brand_id=brand.id)

        sr_old = await make_scan_run(db_session, app_id=app.id, scanned_at=datetime(2023, 5, 1, tzinfo=UTC))
        sr_old = await ingest_pages_and_complete(
            db_session, sr_old.id, [make_axe_payload(url="https://example.com/old")]
        )
        await on_scan_run_completed(db_session, sr_old)
        sr_new = await make_scan_run(db_session, app_id=app.id, scanned_at=datetime(2023, 6, 1, tzinfo=UTC))
        sr_new = await ingest_pages_and_complete(
            db_session, sr_new.id, [make_axe_payload(url="https://example.com/new")]
        )
        await on_scan_run_completed(db_session, sr_new)

        await db_session.delete(sr_new)
        await db_session.flush()
        await on_app_latest_snapshot_changed(db_session, org_unit.id, brand.id)

        cutoff = datetime(2023, 5, 1, tzinfo=UTC)
        ou_snaps = (
            (await db_session.execute(select(ScoreSnapshot).where(ScoreSnapshot.org_unit_id == org_unit.id)))
            .scalars()
            .all()
        )
        assert ou_snaps and all(s.snapshot_at <= cutoff for s in ou_snaps)
        brand_snaps = (
            (await db_session.execute(select(ScoreSnapshot).where(ScoreSnapshot.brand_id == brand.id))).scalars().all()
        )
        assert brand_snaps and all(s.snapshot_at <= cutoff for s in brand_snaps)

    async def test_last_scan_run_deleted(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="Go365")
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(db_session, name="App", slug="app-last-sr", org_unit_id=org_unit.id, brand_id=brand.id)

        sr = await make_scan_run(db_session, app_id=app.id)
        payload = make_axe_payload(violations=[make_violation("r1", "serious")])
        sr = await ingest_pages_and_complete(db_session, sr.id, [payload])
        await on_scan_run_completed(db_session, sr)

        await db_session.delete(sr)
        await db_session.flush()
        await on_app_latest_snapshot_changed(db_session, org_unit.id, brand.id)

        app_result = await db_session.execute(select(ScoreSnapshot).where(ScoreSnapshot.app_id == app.id))
        assert app_result.scalar_one_or_none() is None
        ou_result = await db_session.execute(select(ScoreSnapshot).where(ScoreSnapshot.org_unit_id == org_unit.id))
        assert ou_result.scalar_one_or_none() is None
        brand_result = await db_session.execute(select(ScoreSnapshot).where(ScoreSnapshot.brand_id == brand.id))
        assert brand_result.scalar_one_or_none() is None


class TestOnOrgUnitReparented:
    async def test_rolls_up_both_old_and_new_parent_chains(self, db_session: AsyncSession) -> None:
        root = await make_org_unit(db_session, name="Root")
        branch_a = await make_org_unit(db_session, name="Branch A", parent_id=root.id)
        branch_b = await make_org_unit(db_session, name="Branch B", parent_id=root.id)

        app_a = await make_app(db_session, name="App A", slug="app-a", org_unit_id=branch_a.id)
        await make_score_snapshot(
            db_session,
            app_id=app_a.id,
            score=0.4,
            total_pages=2,
            total_violations=3,
            pages_with_violations=1,
            pages_with_critical_violations=0,
        )

        app_b = await make_app(db_session, name="App B", slug="app-b", org_unit_id=branch_b.id)
        await make_score_snapshot(
            db_session,
            app_id=app_b.id,
            score=1.0,
            total_pages=1,
            total_violations=0,
            pages_with_violations=0,
            pages_with_critical_violations=0,
        )

        child_ou = await make_org_unit(db_session, name="Child", parent_id=branch_a.id)
        app_c = await make_app(db_session, name="App C", slug="app-c", org_unit_id=child_ou.id)
        await make_score_snapshot(
            db_session,
            app_id=app_c.id,
            score=0.8,
            total_pages=5,
            total_violations=1,
            pages_with_violations=1,
            pages_with_critical_violations=0,
        )
        await make_score_snapshot(
            db_session,
            org_unit_id=child_ou.id,
            score=0.8,
            total_pages=5,
            total_violations=1,
            pages_with_violations=1,
            pages_with_critical_violations=0,
        )

        child_ou.parent_id = branch_b.id
        await db_session.flush()

        await on_org_unit_reparented(db_session, child_ou.id, branch_a.id, branch_b.id)

        assert (await latest_ou_snapshot(db_session, branch_b.id)).score == approx((1.0 + 0.8) / 2)
        assert (await latest_ou_snapshot(db_session, branch_a.id)).score == approx(0.4)

    async def test_skips_none_parents(self, db_session: AsyncSession) -> None:
        new_parent = await make_org_unit(db_session, name="New Parent")
        orphan = await make_org_unit(db_session, name="Orphan", parent_id=new_parent.id)

        app = await make_app(db_session, name="App", slug="app-orphan", org_unit_id=orphan.id)
        await make_score_snapshot(
            db_session,
            app_id=app.id,
            score=0.6,
            total_pages=3,
            total_violations=2,
            pages_with_violations=1,
            pages_with_critical_violations=0,
        )
        await make_score_snapshot(
            db_session,
            org_unit_id=orphan.id,
            score=0.6,
            total_pages=3,
            total_violations=2,
            pages_with_violations=1,
            pages_with_critical_violations=0,
        )

        # old_parent_id=None can no longer arise through the org-unit service
        # (single-root invariant), but the orchestration seam stays defensive;
        # exercise the skip directly.
        await on_org_unit_reparented(db_session, orphan.id, None, new_parent.id)

        assert (await latest_ou_snapshot(db_session, new_parent.id)).score == approx(0.6)

    async def test_does_not_trigger_brand_rollup(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="Go365")
        top = await make_org_unit(db_session, name="Top")
        branch_a = await make_org_unit(db_session, name="Branch A", parent_id=top.id)
        branch_b = await make_org_unit(db_session, name="Branch B", parent_id=top.id)

        app = await make_app(db_session, name="App", slug="app-reparent", org_unit_id=branch_a.id, brand_id=brand.id)
        await make_score_snapshot(
            db_session,
            app_id=app.id,
            score=0.6,
            total_pages=3,
            total_violations=2,
            pages_with_violations=1,
            pages_with_critical_violations=0,
        )

        child_ou = await make_org_unit(db_session, name="Child", parent_id=branch_a.id)
        child_ou.parent_id = branch_b.id
        await db_session.flush()

        await on_org_unit_reparented(db_session, child_ou.id, branch_a.id, branch_b.id)

        result = await db_session.execute(select(ScoreSnapshot).where(ScoreSnapshot.brand_id == brand.id))
        assert result.scalar_one_or_none() is None


class TestOnAppDeleted:
    async def test_recalculates_org_unit_rollups(self, db_session: AsyncSession) -> None:
        root = await make_org_unit(db_session, name="Root")
        leaf = await make_org_unit(db_session, name="Leaf", parent_id=root.id)
        brand = await make_brand(db_session, name="Humana")

        app_a = await make_app(db_session, name="App A", slug="app-a", org_unit_id=leaf.id, brand_id=brand.id)
        sr_a = await make_scan_run(db_session, app_id=app_a.id)
        payload_a = make_axe_payload(violations=[make_violation("r1", "serious")])
        sr_a = await ingest_pages_and_complete(db_session, sr_a.id, [payload_a])
        await on_scan_run_completed(db_session, sr_a)

        app_b = await make_app(db_session, name="App B", slug="app-b", org_unit_id=leaf.id, brand_id=brand.id)
        sr_b = await make_scan_run(db_session, app_id=app_b.id)
        payload_b = make_axe_payload(url="https://example.com/b")
        sr_b = await ingest_pages_and_complete(db_session, sr_b.id, [payload_b])
        await on_scan_run_completed(db_session, sr_b)

        leaf_before = await latest_ou_snapshot(db_session, leaf.id)
        assert leaf_before.score == approx(0.7)

        await db_session.delete(app_a)
        await db_session.flush()
        await on_app_latest_snapshot_changed(db_session, leaf.id, brand.id)

        leaf_after = await latest_ou_snapshot(db_session, leaf.id)
        assert leaf_after.score == approx(1.0)
        root_after = await latest_ou_snapshot(db_session, root.id)
        assert root_after.score == approx(1.0)

    async def test_recalculates_brand_rollups(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="CenterWell")
        org_unit = await make_org_unit(db_session, name="Org")

        app_a = await make_app(db_session, name="App A", slug="app-a", org_unit_id=org_unit.id, brand_id=brand.id)
        sr_a = await make_scan_run(db_session, app_id=app_a.id)
        payload_a = make_axe_payload(violations=[make_violation("r1", "serious")])
        sr_a = await ingest_pages_and_complete(db_session, sr_a.id, [payload_a])
        await on_scan_run_completed(db_session, sr_a)

        app_b = await make_app(db_session, name="App B", slug="app-b", org_unit_id=org_unit.id, brand_id=brand.id)
        sr_b = await make_scan_run(db_session, app_id=app_b.id)
        payload_b = make_axe_payload(url="https://example.com/b")
        sr_b = await ingest_pages_and_complete(db_session, sr_b.id, [payload_b])
        await on_scan_run_completed(db_session, sr_b)

        brand_before = await latest_brand_snapshot(db_session, brand.id)
        assert brand_before.score == approx(0.7)

        await db_session.delete(app_a)
        await db_session.flush()
        await on_app_latest_snapshot_changed(db_session, org_unit.id, brand.id)

        brand_after = await latest_brand_snapshot(db_session, brand.id)
        assert brand_after.score == approx(1.0)

    async def test_last_app_deleted_wipes_ou_snapshot(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="Go365")
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(db_session, name="App", slug="app-solo", org_unit_id=org_unit.id, brand_id=brand.id)
        sr = await make_scan_run(db_session, app_id=app.id)
        payload = make_axe_payload(violations=[make_violation("r1", "serious")])
        sr = await ingest_pages_and_complete(db_session, sr.id, [payload])
        await on_scan_run_completed(db_session, sr)

        await db_session.delete(app)
        await db_session.flush()
        await on_app_latest_snapshot_changed(db_session, org_unit.id, brand.id)

        result = await db_session.execute(select(ScoreSnapshot).where(ScoreSnapshot.org_unit_id == org_unit.id))
        assert result.scalar_one_or_none() is None

    async def test_last_app_deleted_wipes_brand_snapshot(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="Go365")
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(db_session, name="App", slug="app-solo-brand", org_unit_id=org_unit.id, brand_id=brand.id)
        sr = await make_scan_run(db_session, app_id=app.id)
        payload = make_axe_payload(violations=[make_violation("r1", "serious")])
        sr = await ingest_pages_and_complete(db_session, sr.id, [payload])
        await on_scan_run_completed(db_session, sr)

        await db_session.delete(app)
        await db_session.flush()
        await on_app_latest_snapshot_changed(db_session, org_unit.id, brand.id)

        result = await db_session.execute(select(ScoreSnapshot).where(ScoreSnapshot.brand_id == brand.id))
        assert result.scalar_one_or_none() is None

    async def test_emptied_branch_wipes_but_root_reflects_sibling(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="Humana")
        root = await make_org_unit(db_session, name="Root")
        branch_a = await make_org_unit(db_session, name="Branch A", parent_id=root.id)
        branch_b = await make_org_unit(db_session, name="Branch B", parent_id=root.id)

        app_a = await make_app(
            db_session, name="App A", slug="app-a-cascade", org_unit_id=branch_a.id, brand_id=brand.id
        )
        sr_a = await make_scan_run(db_session, app_id=app_a.id)
        payload_a = make_axe_payload(violations=[make_violation("r1", "serious")])
        sr_a = await ingest_pages_and_complete(db_session, sr_a.id, [payload_a])
        await on_scan_run_completed(db_session, sr_a)

        app_b = await make_app(
            db_session, name="App B", slug="app-b-cascade", org_unit_id=branch_b.id, brand_id=brand.id
        )
        sr_b = await make_scan_run(db_session, app_id=app_b.id)
        payload_b = make_axe_payload(url="https://example.com/b")
        sr_b = await ingest_pages_and_complete(db_session, sr_b.id, [payload_b])
        await on_scan_run_completed(db_session, sr_b)

        branch_a_before = await latest_ou_snapshot(db_session, branch_a.id)
        assert branch_a_before.score == approx(0.4)

        await db_session.delete(app_a)
        await db_session.flush()
        await on_app_latest_snapshot_changed(db_session, branch_a.id, brand.id)

        result = await db_session.execute(select(ScoreSnapshot).where(ScoreSnapshot.org_unit_id == branch_a.id))
        assert result.scalar_one_or_none() is None

        branch_b_after = await latest_ou_snapshot(db_session, branch_b.id)
        assert branch_b_after.score == approx(1.0)

        root_after = await latest_ou_snapshot(db_session, root.id)
        assert root_after.score == approx(1.0)


class TestOnAppReassigned:
    async def test_recalculates_both_org_units(self, db_session: AsyncSession) -> None:
        top = await make_org_unit(db_session, name="Top")
        org_a = await make_org_unit(db_session, name="Org A", parent_id=top.id)
        org_b = await make_org_unit(db_session, name="Org B", parent_id=top.id)

        app_a = await make_app(db_session, name="App A", slug="app-a", org_unit_id=org_a.id)
        await make_score_snapshot(
            db_session,
            app_id=app_a.id,
            score=0.4,
            total_pages=2,
            total_violations=3,
            pages_with_violations=1,
            pages_with_critical_violations=0,
        )

        app_stay = await make_app(db_session, name="App Stay", slug="app-stay", org_unit_id=org_a.id)
        await make_score_snapshot(
            db_session,
            app_id=app_stay.id,
            score=1.0,
            total_pages=1,
            total_violations=0,
            pages_with_violations=0,
            pages_with_critical_violations=0,
        )

        app_b = await make_app(db_session, name="App B", slug="app-b", org_unit_id=org_b.id)
        await make_score_snapshot(
            db_session,
            app_id=app_b.id,
            score=1.0,
            total_pages=1,
            total_violations=0,
            pages_with_violations=0,
            pages_with_critical_violations=0,
        )

        app_a.org_unit_id = org_b.id
        await db_session.flush()
        await on_app_reassigned(db_session, org_a.id, org_b.id)

        old_snap = await latest_ou_snapshot(db_session, org_a.id)
        assert old_snap.score == approx(1.0)

        new_snap = await latest_ou_snapshot(db_session, org_b.id)
        assert new_snap.score == approx((1.0 + 0.4) / 2)

    async def test_propagates_parent_chains(self, db_session: AsyncSession) -> None:
        top = await make_org_unit(db_session, name="Top")
        root_a = await make_org_unit(db_session, name="Root A", parent_id=top.id)
        leaf_a = await make_org_unit(db_session, name="Leaf A", parent_id=root_a.id)
        root_b = await make_org_unit(db_session, name="Root B", parent_id=top.id)
        leaf_b = await make_org_unit(db_session, name="Leaf B", parent_id=root_b.id)

        app = await make_app(db_session, name="App", slug="app-move", org_unit_id=leaf_a.id)
        await make_score_snapshot(
            db_session,
            app_id=app.id,
            score=0.6,
            total_pages=3,
            total_violations=2,
            pages_with_violations=1,
            pages_with_critical_violations=0,
        )

        app.org_unit_id = leaf_b.id
        await db_session.flush()
        await on_app_reassigned(db_session, leaf_a.id, leaf_b.id)

        leaf_b_snap = await latest_ou_snapshot(db_session, leaf_b.id)
        assert leaf_b_snap.score == approx(0.6)
        root_b_snap = await latest_ou_snapshot(db_session, root_b.id)
        assert root_b_snap.score == approx(0.6)

        result = await db_session.execute(select(ScoreSnapshot).where(ScoreSnapshot.org_unit_id == leaf_a.id))
        assert result.scalar_one_or_none() is None

    async def test_does_not_touch_brand(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="Humana")
        top = await make_org_unit(db_session, name="Top")
        org_a = await make_org_unit(db_session, name="Org A", parent_id=top.id)
        org_b = await make_org_unit(db_session, name="Org B", parent_id=top.id)

        app = await make_app(db_session, name="App", slug="app-brand-noop", org_unit_id=org_a.id, brand_id=brand.id)
        await make_score_snapshot(
            db_session,
            app_id=app.id,
            score=0.6,
            total_pages=3,
            total_violations=2,
            pages_with_violations=1,
            pages_with_critical_violations=0,
        )

        app.org_unit_id = org_b.id
        await db_session.flush()
        await on_app_reassigned(db_session, org_a.id, org_b.id)

        result = await db_session.execute(select(ScoreSnapshot).where(ScoreSnapshot.brand_id == brand.id))
        assert result.scalar_one_or_none() is None
