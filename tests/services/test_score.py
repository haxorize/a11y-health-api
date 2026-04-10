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
from tests.factories import make_axe_payload, make_scan_run_with_parents, make_violation


async def _setup_and_score(db_session: AsyncSession, *payloads: dict) -> tuple[list[PageResult], ScoreSnapshot]:
    scan_run = await make_scan_run_with_parents(db_session)
    for payload in payloads:
        await create_page_result(db_session, scan_run.id, payload)

    scan_run.status = ScanRunStatus.COMPLETED
    await db_session.flush()
    scan_run = await get_scan_run(db_session, scan_run.id)

    snapshot = await compute_scores(db_session, scan_run)

    result = await db_session.execute(select(PageResult).where(PageResult.scan_run_id == scan_run.id))
    return list(result.scalars().all()), snapshot


class TestPageHealthCategorization:
    async def test_critical_violation_gives_critical_health(self, db_session: AsyncSession):
        pages, _ = await _setup_and_score(
            db_session, make_axe_payload(violations=[make_violation("rule-1", "critical")])
        )
        assert pages[0].page_health == PageHealth.CRITICAL

    async def test_serious_violation_gives_serious_health(self, db_session: AsyncSession):
        pages, _ = await _setup_and_score(
            db_session, make_axe_payload(violations=[make_violation("rule-1", "serious")])
        )
        assert pages[0].page_health == PageHealth.SERIOUS

    async def test_moderate_violation_gives_fair_health(self, db_session: AsyncSession):
        pages, _ = await _setup_and_score(
            db_session, make_axe_payload(violations=[make_violation("rule-1", "moderate")])
        )
        assert pages[0].page_health == PageHealth.FAIR

    async def test_minor_violation_gives_good_health(self, db_session: AsyncSession):
        """Minor violations don't count against the score."""
        pages, _ = await _setup_and_score(db_session, make_axe_payload(violations=[make_violation("rule-1", "minor")]))
        assert pages[0].page_health == PageHealth.GOOD

    async def test_no_violations_gives_good_health(self, db_session: AsyncSession):
        pages, _ = await _setup_and_score(db_session, make_axe_payload())
        assert pages[0].page_health == PageHealth.GOOD

    async def test_worst_severity_wins(self, db_session: AsyncSession):
        """A page with both minor and critical violations gets CRITICAL."""
        pages, _ = await _setup_and_score(
            db_session,
            make_axe_payload(violations=[make_violation("rule-1", "minor"), make_violation("rule-2", "critical")]),
        )
        assert pages[0].page_health == PageHealth.CRITICAL


class TestIncompleteExcluded:
    async def test_only_incomplete_findings_gives_good_health(self, db_session: AsyncSession):
        """Incomplete findings are excluded from page health — page should be GOOD."""
        pages, _ = await _setup_and_score(
            db_session,
            make_axe_payload(incomplete=[make_violation("rule-1", "critical")]),
        )
        assert pages[0].page_health == PageHealth.GOOD

    async def test_incomplete_does_not_worsen_violation_health(self, db_session: AsyncSession):
        """A critical incomplete alongside a moderate violation should give FAIR, not CRITICAL."""
        pages, _ = await _setup_and_score(
            db_session,
            make_axe_payload(
                violations=[make_violation("rule-1", "moderate")],
                incomplete=[make_violation("rule-2", "critical")],
            ),
        )
        assert pages[0].page_health == PageHealth.FAIR


class TestAppScoreFormula:
    async def test_all_good_pages_score_1(self, db_session: AsyncSession):
        """3 pages with no violations → score = (1+1+1)/3 = 1.0"""
        _, snapshot = await _setup_and_score(
            db_session,
            make_axe_payload(url="https://example.com/a"),
            make_axe_payload(url="https://example.com/b"),
            make_axe_payload(url="https://example.com/c"),
        )
        assert snapshot.score == approx(1.0)

    async def test_all_critical_pages_score_0(self, db_session: AsyncSession):
        """2 pages with critical violations → score = (0+0)/2 = 0.0"""
        _, snapshot = await _setup_and_score(
            db_session,
            make_axe_payload(url="https://example.com/a", violations=[make_violation("r1", "critical")]),
            make_axe_payload(url="https://example.com/b", violations=[make_violation("r2", "critical")]),
        )
        assert snapshot.score == approx(0.0)

    async def test_mixed_pages_weighted_average(self, db_session: AsyncSession):
        """1 critical(0) + 1 serious(0.4) + 1 fair(0.8) + 1 good(1.0) → (0+0.4+0.8+1.0)/4 = 0.55"""
        _, snapshot = await _setup_and_score(
            db_session,
            make_axe_payload(url="https://example.com/a", violations=[make_violation("r1", "critical")]),
            make_axe_payload(url="https://example.com/b", violations=[make_violation("r2", "serious")]),
            make_axe_payload(url="https://example.com/c", violations=[make_violation("r3", "moderate")]),
            make_axe_payload(url="https://example.com/d"),
        )
        assert snapshot.score == approx(0.55)


class TestScoreSnapshotMetrics:
    async def test_all_metrics_computed(self, db_session: AsyncSession):
        """Verify all 8 metrics on the snapshot with known inputs."""
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
    async def test_completing_run_creates_snapshot(self, db_session: AsyncSession):
        """Patching status to COMPLETED triggers score computation end-to-end."""
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
    async def test_best_practice_counts_at_severity_level(self, db_session: AsyncSession):
        """Best-practice violations count toward scoring based on their severity."""
        pages, snapshot = await _setup_and_score(
            db_session,
            make_axe_payload(violations=[make_violation("bp-rule", "critical")]),
        )
        assert pages[0].page_health == PageHealth.CRITICAL
        assert snapshot.score == approx(0.0)
