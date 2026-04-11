from datetime import UTC, datetime

from pytest import approx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.page_result import PageHealth, PageResult
from a11y_health.models.scan_run import ScanRunStatus
from a11y_health.models.score_snapshot import ScoreSnapshot
from a11y_health.schemas.scan_run import ScanRunStatusUpdate
from a11y_health.services.page_result import create_page_result
from a11y_health.services.scan_run import get_scan_run, update_scan_run_status
from a11y_health.services.score import compute_scores
from tests.factories import (
    make_app,
    make_axe_payload,
    make_org_unit,
    make_scan_run,
    make_scan_run_with_parents,
    make_violation,
)


async def _ingest_and_score(db_session: AsyncSession, scan_run_id: int, payloads: list[dict]) -> ScoreSnapshot:
    for payload in payloads:
        await create_page_result(db_session, scan_run_id, payload)
    sr = await get_scan_run(db_session, scan_run_id)
    sr.status = ScanRunStatus.COMPLETED
    await db_session.flush()
    return await compute_scores(db_session, sr)


async def _setup_and_score(db_session: AsyncSession, *payloads: dict) -> tuple[list[PageResult], ScoreSnapshot]:
    scan_run = await make_scan_run_with_parents(db_session)
    snapshot = await _ingest_and_score(db_session, scan_run.id, list(payloads))

    result = await db_session.execute(select(PageResult).where(PageResult.scan_run_id == scan_run.id))
    return list(result.scalars().all()), snapshot


class TestPageHealthCategorization:
    async def test_critical_violation_gives_critical_health(self, db_session: AsyncSession) -> None:
        pages, _ = await _setup_and_score(
            db_session, make_axe_payload(violations=[make_violation("rule-1", "critical")])
        )
        assert pages[0].page_health == PageHealth.CRITICAL

    async def test_serious_violation_gives_serious_health(self, db_session: AsyncSession) -> None:
        pages, _ = await _setup_and_score(
            db_session, make_axe_payload(violations=[make_violation("rule-1", "serious")])
        )
        assert pages[0].page_health == PageHealth.SERIOUS

    async def test_moderate_violation_gives_fair_health(self, db_session: AsyncSession) -> None:
        pages, _ = await _setup_and_score(
            db_session, make_axe_payload(violations=[make_violation("rule-1", "moderate")])
        )
        assert pages[0].page_health == PageHealth.FAIR

    async def test_minor_violation_gives_good_health(self, db_session: AsyncSession) -> None:
        pages, _ = await _setup_and_score(db_session, make_axe_payload(violations=[make_violation("rule-1", "minor")]))
        assert pages[0].page_health == PageHealth.GOOD

    async def test_no_violations_gives_good_health(self, db_session: AsyncSession) -> None:
        pages, _ = await _setup_and_score(db_session, make_axe_payload())
        assert pages[0].page_health == PageHealth.GOOD

    async def test_worst_severity_wins(self, db_session: AsyncSession) -> None:
        pages, _ = await _setup_and_score(
            db_session,
            make_axe_payload(violations=[make_violation("rule-1", "minor"), make_violation("rule-2", "critical")]),
        )
        assert pages[0].page_health == PageHealth.CRITICAL


class TestIncompleteExcluded:
    async def test_only_incomplete_findings_gives_good_health(self, db_session: AsyncSession) -> None:
        pages, _ = await _setup_and_score(
            db_session,
            make_axe_payload(incomplete=[make_violation("rule-1", "critical")]),
        )
        assert pages[0].page_health == PageHealth.GOOD

    async def test_incomplete_does_not_worsen_violation_health(self, db_session: AsyncSession) -> None:
        pages, _ = await _setup_and_score(
            db_session,
            make_axe_payload(
                violations=[make_violation("rule-1", "moderate")],
                incomplete=[make_violation("rule-2", "critical")],
            ),
        )
        assert pages[0].page_health == PageHealth.FAIR


class TestAppScoreFormula:
    async def test_all_good_pages_score_1(self, db_session: AsyncSession) -> None:
        _, snapshot = await _setup_and_score(
            db_session,
            make_axe_payload(url="https://example.com/a"),
            make_axe_payload(url="https://example.com/b"),
            make_axe_payload(url="https://example.com/c"),
        )
        assert snapshot.score == approx(1.0)

    async def test_all_critical_pages_score_0(self, db_session: AsyncSession) -> None:
        _, snapshot = await _setup_and_score(
            db_session,
            make_axe_payload(url="https://example.com/a", violations=[make_violation("r1", "critical")]),
            make_axe_payload(url="https://example.com/b", violations=[make_violation("r2", "critical")]),
        )
        assert snapshot.score == approx(0.0)

    async def test_mixed_pages_weighted_average(self, db_session: AsyncSession) -> None:
        _, snapshot = await _setup_and_score(
            db_session,
            make_axe_payload(url="https://example.com/a", violations=[make_violation("r1", "critical")]),
            make_axe_payload(url="https://example.com/b", violations=[make_violation("r2", "serious")]),
            make_axe_payload(url="https://example.com/c", violations=[make_violation("r3", "moderate")]),
            make_axe_payload(url="https://example.com/d"),
        )
        assert snapshot.score == approx(0.55)


class TestScoreSnapshotMetrics:
    async def test_all_metrics_computed(self, db_session: AsyncSession) -> None:
        _, snapshot = await _setup_and_score(
            db_session,
            make_axe_payload(
                url="https://example.com/a",
                violations=[make_violation("r1", "critical"), make_violation("r2", "serious")],
            ),
            make_axe_payload(url="https://example.com/b"),
            make_axe_payload(
                url="https://example.com/c",
                violations=[make_violation("r3", "serious")],
            ),
        )
        assert snapshot.score == approx(1.4 / 3)
        assert snapshot.total_issues == 3
        assert snapshot.pages_with_issues == 2
        assert snapshot.pages_with_critical_issues == 1
        assert snapshot.total_pages == 3
        assert snapshot.avg_issues_per_page == approx(1.0)
        assert snapshot.pct_pages_with_issues == approx(2 / 3)
        assert snapshot.pct_pages_with_critical_issues == approx(1 / 3)


class TestStatusUpdateTriggersScoring:
    async def test_completing_run_creates_snapshot(self, db_session: AsyncSession) -> None:
        scan_run = await make_scan_run_with_parents(db_session)
        await create_page_result(
            db_session,
            scan_run.id,
            make_axe_payload(violations=[make_violation("r1", "serious")]),
        )

        await update_scan_run_status(db_session, scan_run.id, ScanRunStatusUpdate(status=ScanRunStatus.COMPLETED))

        result = await db_session.execute(select(ScoreSnapshot).where(ScoreSnapshot.scan_run_id == scan_run.id))
        snapshot = result.scalar_one()
        assert snapshot.score == approx(0.4)
        assert snapshot.total_pages == 1

        page_result = await db_session.execute(select(PageResult).where(PageResult.scan_run_id == scan_run.id))
        page = page_result.scalar_one()
        assert page.page_health == PageHealth.SERIOUS


class TestBestPracticeViolations:
    async def test_best_practice_counts_at_severity_level(self, db_session: AsyncSession) -> None:
        pages, snapshot = await _setup_and_score(
            db_session,
            make_axe_payload(violations=[make_violation("bp-rule", "critical")]),
        )
        assert pages[0].page_health == PageHealth.CRITICAL
        assert snapshot.score == approx(0.0)


async def _complete_and_score(
    db_session: AsyncSession,
    app_id: int,
    payloads: list[dict],
    scanned_at: datetime | None = None,
) -> ScoreSnapshot:
    sr = await make_scan_run(db_session, app_id=app_id, scanned_at=scanned_at)
    return await _ingest_and_score(db_session, sr.id, payloads)


async def _latest_ou_snapshot(db_session: AsyncSession, org_unit_id: int) -> ScoreSnapshot:
    result = await db_session.execute(
        select(ScoreSnapshot).where(ScoreSnapshot.org_unit_id == org_unit_id).order_by(ScoreSnapshot.id.desc()).limit(1)
    )
    return result.scalar_one()


class TestOrgUnitRollup:
    async def test_single_app_rollup_matches_app_snapshot(self, db_session: AsyncSession) -> None:
        # org_unit -> app -> scan_run with one serious violation
        org_unit = await make_org_unit(db_session, name="Parent Org")
        app = await make_app(db_session, name="App A", slug="app-a", org_unit_id=org_unit.id)
        app_snapshot = await _complete_and_score(
            db_session, app.id, [make_axe_payload(violations=[make_violation("r1", "serious")])]
        )

        ou_snapshot = await _latest_ou_snapshot(db_session, org_unit.id)
        assert ou_snapshot.score == approx(app_snapshot.score)
        assert ou_snapshot.total_issues == app_snapshot.total_issues
        assert ou_snapshot.total_pages == app_snapshot.total_pages
        assert ou_snapshot.pages_with_issues == app_snapshot.pages_with_issues
        assert ou_snapshot.pages_with_critical_issues == app_snapshot.pages_with_critical_issues
        assert ou_snapshot.avg_issues_per_page == approx(app_snapshot.avg_issues_per_page)
        assert ou_snapshot.pct_pages_with_issues == approx(app_snapshot.pct_pages_with_issues)
        assert ou_snapshot.pct_pages_with_critical_issues == approx(app_snapshot.pct_pages_with_critical_issues)

    async def test_two_apps_rollup_averages_scores_sums_counts(self, db_session: AsyncSession) -> None:
        # org_unit -> app_a (score 0.4, serious) + app_b (score 1.0, clean)
        org_unit = await make_org_unit(db_session, name="Parent Org")
        app_a = await make_app(db_session, name="App A", slug="app-a", org_unit_id=org_unit.id)
        app_b = await make_app(db_session, name="App B", slug="app-b", org_unit_id=org_unit.id)

        await _complete_and_score(
            db_session,
            app_a.id,
            [make_axe_payload(violations=[make_violation("r1", "serious")])],
            scanned_at=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
        )
        await _complete_and_score(
            db_session,
            app_b.id,
            [make_axe_payload(url="https://example.com/b")],
            scanned_at=datetime(2026, 4, 1, 13, 0, 0, tzinfo=UTC),
        )

        ou_snapshot = await _latest_ou_snapshot(db_session, org_unit.id)

        # score = mean(0.4, 1.0) = 0.7
        assert ou_snapshot.score == approx(0.7)
        # counts are sums: 1+0 issues, 1+1 pages, 1+0 with issues, 0+0 critical
        assert ou_snapshot.total_issues == 1
        assert ou_snapshot.total_pages == 2
        assert ou_snapshot.pages_with_issues == 1
        assert ou_snapshot.pages_with_critical_issues == 0
        assert ou_snapshot.avg_issues_per_page == approx(0.5)
        assert ou_snapshot.pct_pages_with_issues == approx(0.5)
        assert ou_snapshot.pct_pages_with_critical_issues == approx(0.0)

    async def test_multi_level_tree_cascades_to_root(self, db_session: AsyncSession) -> None:
        # root -> middle -> leaf (org units), app under leaf
        root = await make_org_unit(db_session, name="Root")
        middle = await make_org_unit(db_session, name="Middle", parent_id=root.id)
        leaf = await make_org_unit(db_session, name="Leaf", parent_id=middle.id)
        app = await make_app(db_session, name="App", slug="app-leaf", org_unit_id=leaf.id)

        app_snapshot = await _complete_and_score(
            db_session, app.id, [make_axe_payload(violations=[make_violation("r1", "serious")])]
        )

        # all three org units should have snapshots with the same score
        for ou in [leaf, middle, root]:
            ou_snap = await _latest_ou_snapshot(db_session, ou.id)
            assert ou_snap.score == approx(app_snapshot.score)
            assert ou_snap.total_issues == app_snapshot.total_issues
            assert ou_snap.total_pages == app_snapshot.total_pages

    async def test_mixed_children_org_units_and_apps(self, db_session: AsyncSession) -> None:
        # parent has a direct app (score 0.0) and a child org unit with its own app (score 1.0)
        # parent score = mean(app_score=0.0, child_ou_score=1.0) = 0.5
        parent = await make_org_unit(db_session, name="Parent")
        child_ou = await make_org_unit(db_session, name="Child OU", parent_id=parent.id)
        direct_app = await make_app(db_session, name="Direct App", slug="direct", org_unit_id=parent.id)
        nested_app = await make_app(db_session, name="Nested App", slug="nested", org_unit_id=child_ou.id)

        await _complete_and_score(
            db_session,
            nested_app.id,
            [make_axe_payload(url="https://example.com/nested")],
            scanned_at=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
        )
        await _complete_and_score(
            db_session,
            direct_app.id,
            [make_axe_payload(url="https://example.com/direct", violations=[make_violation("r1", "critical")])],
            scanned_at=datetime(2026, 4, 1, 13, 0, 0, tzinfo=UTC),
        )

        assert (await _latest_ou_snapshot(db_session, child_ou.id)).score == approx(1.0)

        parent_snap = await _latest_ou_snapshot(db_session, parent.id)
        assert parent_snap.score == approx(0.5)
        assert parent_snap.total_issues == 1
        assert parent_snap.total_pages == 2
        assert parent_snap.pages_with_critical_issues == 1

    async def test_only_latest_app_snapshot_counts(self, db_session: AsyncSession) -> None:
        # app has two scan runs; only the latest snapshot should be used for rollup
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(db_session, name="App", slug="app-latest", org_unit_id=org_unit.id)

        await _complete_and_score(
            db_session,
            app.id,
            [make_axe_payload(violations=[make_violation("r1", "critical")])],
            scanned_at=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
        )
        await _complete_and_score(
            db_session,
            app.id,
            [make_axe_payload(url="https://example.com/b")],
            scanned_at=datetime(2026, 4, 1, 13, 0, 0, tzinfo=UTC),
        )

        # org unit should reflect the latest score (1.0), not the old one (0.0)
        assert (await _latest_ou_snapshot(db_session, org_unit.id)).score == approx(1.0)
