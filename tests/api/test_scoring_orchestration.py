from httpx import AsyncClient
from pytest import approx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.enums import ScanRunStatus
from a11y_health.models.score_snapshot import ScoreSnapshot
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


class TestScanRunCompletionTriggersScoring:
    async def test_completing_scan_run_creates_app_and_rollup_snapshots(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        root = await make_org_unit(db_session, name="Root")
        middle = await make_org_unit(db_session, name="Middle", parent_id=root.id)
        leaf = await make_org_unit(db_session, name="Leaf", parent_id=middle.id)
        app = await make_app(db_session, name="App", slug="app-1", org_unit_id=leaf.id)
        scan_run = await make_scan_run(db_session, app_id=app.id)

        payload = make_axe_payload(violations=[make_violation("r1", "serious")])
        resp = await db_client.post(f"/api/v1/scan-runs/{scan_run.id}/pages", json=payload)
        assert resp.status_code == 201

        resp = await db_client.patch(f"/api/v1/scan-runs/{scan_run.id}", json={"status": ScanRunStatus.COMPLETED.value})
        assert resp.status_code == 200

        app_snap = await db_session.execute(select(ScoreSnapshot).where(ScoreSnapshot.app_id == app.id))
        app_snapshot = app_snap.scalar_one()
        assert app_snapshot.score == approx(0.4)
        assert app_snapshot.total_pages == 1

        for ou in [leaf, middle, root]:
            snapshot = await latest_ou_snapshot(db_session, ou.id)
            assert snapshot.score == approx(0.4)


class TestScanRunCompletionTriggersBrandRollup:
    async def test_completing_scan_run_creates_brand_snapshot(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        brand = await make_brand(db_session, name="Humana")
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(db_session, name="App", slug="app-brand", org_unit_id=org_unit.id, brand_id=brand.id)
        scan_run = await make_scan_run(db_session, app_id=app.id)

        payload = make_axe_payload(violations=[make_violation("r1", "serious")])
        resp = await db_client.post(f"/api/v1/scan-runs/{scan_run.id}/pages", json=payload)
        assert resp.status_code == 201

        resp = await db_client.patch(f"/api/v1/scan-runs/{scan_run.id}", json={"status": ScanRunStatus.COMPLETED.value})
        assert resp.status_code == 200

        brand_snap = await latest_brand_snapshot(db_session, brand.id)
        assert brand_snap.score == approx(0.4)
        assert brand_snap.total_pages == 1

    async def test_second_app_scan_updates_brand_snapshot(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
        brand = await make_brand(db_session, name="CenterWell")
        org_unit = await make_org_unit(db_session, name="Org")
        app_a = await make_app(db_session, name="App A", slug="app-a", org_unit_id=org_unit.id, brand_id=brand.id)
        app_b = await make_app(db_session, name="App B", slug="app-b", org_unit_id=org_unit.id, brand_id=brand.id)

        sr_a = await make_scan_run(db_session, app_id=app_a.id)
        payload_a = make_axe_payload(violations=[make_violation("r1", "serious")])
        await db_client.post(f"/api/v1/scan-runs/{sr_a.id}/pages", json=payload_a)
        await db_client.patch(f"/api/v1/scan-runs/{sr_a.id}", json={"status": ScanRunStatus.COMPLETED.value})

        sr_b = await make_scan_run(db_session, app_id=app_b.id)
        payload_b = make_axe_payload(url="https://example.com/b")
        await db_client.post(f"/api/v1/scan-runs/{sr_b.id}/pages", json=payload_b)
        await db_client.patch(f"/api/v1/scan-runs/{sr_b.id}", json={"status": ScanRunStatus.COMPLETED.value})

        brand_snap = await latest_brand_snapshot(db_session, brand.id)
        assert brand_snap.score == approx(0.7)
        assert brand_snap.total_pages == 2


class TestReparentTriggersRollup:
    async def test_reparenting_rolls_up_both_old_and_new_parent_chains(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
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

        resp = await db_client.patch(
            f"/api/v1/org-units/{child_ou.id}",
            json={"parent_id": branch_b.id},
        )
        assert resp.status_code == 200

        assert (await latest_ou_snapshot(db_session, branch_b.id)).score == approx((1.0 + 0.8) / 2)
        assert (await latest_ou_snapshot(db_session, branch_a.id)).score == approx(0.4)

    async def test_reparenting_app_does_not_trigger_brand_rollup(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
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
        resp = await db_client.patch(f"/api/v1/org-units/{child_ou.id}", json={"parent_id": branch_b.id})
        assert resp.status_code == 200

        result = await db_session.execute(select(ScoreSnapshot).where(ScoreSnapshot.brand_id == brand.id))
        assert result.scalar_one_or_none() is None

    async def test_reparenting_root_org_unit_only_rolls_up_new_chain(
        self, db_client: AsyncClient, db_session: AsyncSession
    ) -> None:
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

        resp = await db_client.patch(
            f"/api/v1/org-units/{orphan.id}",
            json={"parent_id": new_parent.id},
        )
        assert resp.status_code == 200

        assert (await latest_ou_snapshot(db_session, new_parent.id)).score == approx(0.6)
