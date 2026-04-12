from datetime import UTC, datetime

from pytest import approx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.enums import ScanRunStatus
from a11y_health.models.score_snapshot import ScoreSnapshot
from a11y_health.schemas.axe_payload import AxePayload
from a11y_health.services.page_result import create_page_result
from a11y_health.services.scan_run import get_scan_run
from a11y_health.services.scoring_orchestration import (
    on_app_deleted,
    on_app_reassigned,
    on_org_unit_reparented,
    on_scan_run_completed,
    on_scan_run_deleted,
)
from tests.factories import (
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


async def _complete_scan_run(db: AsyncSession, scan_run_id: int, payloads: list[dict]) -> None:
    for raw in payloads:
        await create_page_result(db, scan_run_id, AxePayload.model_validate(raw), raw)
    sr = await get_scan_run(db, scan_run_id)
    sr.status = ScanRunStatus.COMPLETED
    await db.flush()
    await on_scan_run_completed(db, sr)


class TestOnScanRunCompleted:
    async def test_creates_app_and_rollup_snapshots(self, db_session: AsyncSession) -> None:
        root = await make_org_unit(db_session, name="Root")
        middle = await make_org_unit(db_session, name="Middle", parent_id=root.id)
        leaf = await make_org_unit(db_session, name="Leaf", parent_id=middle.id)
        app = await make_app(db_session, name="App", slug="app-1", org_unit_id=leaf.id)
        scan_run = await make_scan_run(db_session, app_id=app.id)

        payload = make_axe_payload(violations=[make_violation("r1", "serious")])
        await _complete_scan_run(db_session, scan_run.id, [payload])

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
        await _complete_scan_run(db_session, scan_run.id, [payload])

        brand_snap = await latest_brand_snapshot(db_session, brand.id)
        assert brand_snap.score == approx(0.4)
        assert brand_snap.total_pages == 1

    async def test_multi_app_brand(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="CenterWell")
        org_unit = await make_org_unit(db_session, name="Org")
        app_a = await make_app(db_session, name="App A", slug="app-a", org_unit_id=org_unit.id, brand_id=brand.id)
        app_b = await make_app(db_session, name="App B", slug="app-b", org_unit_id=org_unit.id, brand_id=brand.id)

        payload_a = make_axe_payload(violations=[make_violation("r1", "serious")])
        sr_a = await make_scan_run(db_session, app_id=app_a.id)
        await _complete_scan_run(db_session, sr_a.id, [payload_a])

        payload_b = make_axe_payload(url="https://example.com/b")
        sr_b = await make_scan_run(db_session, app_id=app_b.id)
        await _complete_scan_run(db_session, sr_b.id, [payload_b])

        brand_snap = await latest_brand_snapshot(db_session, brand.id)
        assert brand_snap.score == approx(0.7)
        assert brand_snap.total_pages == 2


class TestOnScanRunDeleted:
    async def test_recomputes_app_score_from_remaining_run(self, db_session: AsyncSession) -> None:
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(db_session, name="App", slug="app-recomp", org_unit_id=org_unit.id)

        sr_a = await make_scan_run(db_session, app_id=app.id, scanned_at=datetime(2026, 3, 1, tzinfo=UTC))
        payload_a = make_axe_payload(violations=[make_violation("r1", "serious")])
        await _complete_scan_run(db_session, sr_a.id, [payload_a])

        sr_b = await make_scan_run(db_session, app_id=app.id, scanned_at=datetime(2026, 4, 1, tzinfo=UTC))
        payload_b = make_axe_payload(url="https://example.com/b")
        await _complete_scan_run(db_session, sr_b.id, [payload_b])

        await db_session.delete(sr_b)
        await db_session.flush()
        await on_scan_run_deleted(db_session, app.id, org_unit.id, app.brand_id)

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
        await _complete_scan_run(db_session, sr_a.id, [payload_a])

        sr_b = await make_scan_run(db_session, app_id=app.id, scanned_at=datetime(2026, 4, 1, tzinfo=UTC))
        payload_b = make_axe_payload(url="https://example.com/b")
        await _complete_scan_run(db_session, sr_b.id, [payload_b])

        leaf_before = await latest_ou_snapshot(db_session, leaf.id)
        assert leaf_before.score == approx(1.0)

        await db_session.delete(sr_b)
        await db_session.flush()
        await on_scan_run_deleted(db_session, app.id, leaf.id, app.brand_id)

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
        await _complete_scan_run(db_session, sr_a.id, [payload_a])

        sr_b = await make_scan_run(db_session, app_id=app.id, scanned_at=datetime(2026, 4, 1, tzinfo=UTC))
        payload_b = make_axe_payload(url="https://example.com/b")
        await _complete_scan_run(db_session, sr_b.id, [payload_b])

        brand_before = await latest_brand_snapshot(db_session, brand.id)
        assert brand_before.score == approx(1.0)

        await db_session.delete(sr_b)
        await db_session.flush()
        await on_scan_run_deleted(db_session, app.id, org_unit.id, brand.id)

        brand_after = await latest_brand_snapshot(db_session, brand.id)
        assert brand_after.score == approx(0.4)

    async def test_last_scan_run_deleted(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="Go365")
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(db_session, name="App", slug="app-last-sr", org_unit_id=org_unit.id, brand_id=brand.id)

        sr = await make_scan_run(db_session, app_id=app.id)
        payload = make_axe_payload(violations=[make_violation("r1", "serious")])
        await _complete_scan_run(db_session, sr.id, [payload])

        await db_session.delete(sr)
        await db_session.flush()
        await on_scan_run_deleted(db_session, app.id, org_unit.id, brand.id)

        result = await db_session.execute(select(ScoreSnapshot).where(ScoreSnapshot.app_id == app.id))
        assert result.scalar_one_or_none() is None


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
        orphan = await make_org_unit(db_session, name="Orphan")

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

        orphan.parent_id = new_parent.id
        await db_session.flush()

        await on_org_unit_reparented(db_session, orphan.id, None, new_parent.id)

        assert (await latest_ou_snapshot(db_session, new_parent.id)).score == approx(0.6)

    async def test_does_not_trigger_brand_rollup(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="Go365")
        branch_a = await make_org_unit(db_session, name="Branch A")
        branch_b = await make_org_unit(db_session, name="Branch B")

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
        await _complete_scan_run(db_session, sr_a.id, [payload_a])

        app_b = await make_app(db_session, name="App B", slug="app-b", org_unit_id=leaf.id, brand_id=brand.id)
        sr_b = await make_scan_run(db_session, app_id=app_b.id)
        payload_b = make_axe_payload(url="https://example.com/b")
        await _complete_scan_run(db_session, sr_b.id, [payload_b])

        leaf_before = await latest_ou_snapshot(db_session, leaf.id)
        assert leaf_before.score == approx(0.7)

        await db_session.delete(app_a)
        await db_session.flush()
        await on_app_deleted(db_session, leaf.id, brand.id)

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
        await _complete_scan_run(db_session, sr_a.id, [payload_a])

        app_b = await make_app(db_session, name="App B", slug="app-b", org_unit_id=org_unit.id, brand_id=brand.id)
        sr_b = await make_scan_run(db_session, app_id=app_b.id)
        payload_b = make_axe_payload(url="https://example.com/b")
        await _complete_scan_run(db_session, sr_b.id, [payload_b])

        brand_before = await latest_brand_snapshot(db_session, brand.id)
        assert brand_before.score == approx(0.7)

        await db_session.delete(app_a)
        await db_session.flush()
        await on_app_deleted(db_session, org_unit.id, brand.id)

        brand_after = await latest_brand_snapshot(db_session, brand.id)
        assert brand_after.score == approx(1.0)

    async def test_last_app_deleted_does_not_error(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="Go365")
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(db_session, name="App", slug="app-solo", org_unit_id=org_unit.id, brand_id=brand.id)
        sr = await make_scan_run(db_session, app_id=app.id)
        payload = make_axe_payload(violations=[make_violation("r1", "serious")])
        await _complete_scan_run(db_session, sr.id, [payload])

        await db_session.delete(app)
        await db_session.flush()
        await on_app_deleted(db_session, org_unit.id, brand.id)


class TestOnAppReassigned:
    async def test_recalculates_both_org_units(self, db_session: AsyncSession) -> None:
        org_a = await make_org_unit(db_session, name="Org A")
        org_b = await make_org_unit(db_session, name="Org B")

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
        root_a = await make_org_unit(db_session, name="Root A")
        leaf_a = await make_org_unit(db_session, name="Leaf A", parent_id=root_a.id)
        root_b = await make_org_unit(db_session, name="Root B")
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
        org_a = await make_org_unit(db_session, name="Org A")
        org_b = await make_org_unit(db_session, name="Org B")

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
