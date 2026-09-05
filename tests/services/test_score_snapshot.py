from pytest import approx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.enums import Impact, PageHealth
from a11y_health.models.page_result import PageResult
from a11y_health.services.score_snapshot import (
    compute_app_score,
    compute_app_score_result,
    compute_page_health,
)
from tests.factories import (
    ingest_and_score,
    ingest_pages_and_complete,
    make_axe_payload,
    make_scan_run_with_parents,
    make_violation,
)


class TestComputePageHealth:
    def test_critical_impact_gives_critical_health(self) -> None:
        assert compute_page_health([Impact.CRITICAL]) == PageHealth.CRITICAL

    def test_serious_impact_gives_serious_health(self) -> None:
        assert compute_page_health([Impact.SERIOUS]) == PageHealth.SERIOUS

    def test_moderate_impact_gives_fair_health(self) -> None:
        assert compute_page_health([Impact.MODERATE]) == PageHealth.FAIR

    def test_minor_impact_gives_good_health(self) -> None:
        assert compute_page_health([Impact.MINOR]) == PageHealth.GOOD

    def test_empty_list_gives_good_health(self) -> None:
        assert compute_page_health([]) == PageHealth.GOOD

    def test_worst_impact_wins(self) -> None:
        assert compute_page_health([Impact.MINOR, Impact.CRITICAL]) == PageHealth.CRITICAL


class TestComputeAppScoreResult:
    def test_all_good_pages_score_1(self) -> None:
        result = compute_app_score_result(
            page_ids=[1, 2, 3],
            violations_by_page={},
        )
        assert result.aggregates.score == approx(1.0)
        assert result.page_healths == {1: PageHealth.GOOD, 2: PageHealth.GOOD, 3: PageHealth.GOOD}

    def test_all_critical_pages_score_0(self) -> None:
        result = compute_app_score_result(
            page_ids=[1, 2],
            violations_by_page={1: [Impact.CRITICAL], 2: [Impact.CRITICAL]},
        )
        assert result.aggregates.score == approx(0.0)

    def test_mixed_pages_weighted_average(self) -> None:
        result = compute_app_score_result(
            page_ids=[1, 2, 3, 4],
            violations_by_page={
                1: [Impact.CRITICAL],
                2: [Impact.SERIOUS],
                3: [Impact.MODERATE],
            },
        )
        assert result.aggregates.score == approx(0.55)
        assert result.page_healths[4] == PageHealth.GOOD

    def test_zero_pages_returns_zero_score(self) -> None:
        result = compute_app_score_result(page_ids=[], violations_by_page={})
        assert result.aggregates.score == approx(0.0)
        assert result.aggregates.total_pages == 0

    def test_metric_accumulation(self) -> None:
        result = compute_app_score_result(
            page_ids=[1, 2, 3],
            violations_by_page={
                1: [Impact.CRITICAL, Impact.SERIOUS],
                3: [Impact.SERIOUS],
            },
        )
        assert result.aggregates.total_violations == 3
        assert result.aggregates.total_pages == 3
        assert result.aggregates.pages_with_violations == 2
        assert result.aggregates.pages_with_critical_violations == 1
        assert result.page_healths[1] == PageHealth.CRITICAL
        assert result.page_healths[2] == PageHealth.GOOD
        assert result.page_healths[3] == PageHealth.SERIOUS


class TestScoreSnapshotMetrics:
    async def test_snapshot_stores_counts_and_score(self, db_session: AsyncSession) -> None:
        scan_run = await make_scan_run_with_parents(db_session)
        axe_payloads = [
            make_axe_payload(
                url="https://example.com/a",
                violations=[make_violation("r1", "critical"), make_violation("r2", "serious")],
            ),
            make_axe_payload(url="https://example.com/b"),
            make_axe_payload(url="https://example.com/c", violations=[make_violation("r3", "serious")]),
        ]

        snapshot = await ingest_and_score(db_session, scan_run.id, axe_payloads)

        assert snapshot.score == approx(1.4 / 3)
        assert snapshot.total_violations == 3
        assert snapshot.pages_with_violations == 2
        assert snapshot.pages_with_critical_violations == 1
        assert snapshot.total_pages == 3


class TestComputeAppScoreCreatesSnapshot:
    async def test_creates_snapshot_with_correct_metrics(self, db_session: AsyncSession) -> None:
        scan_run = await make_scan_run_with_parents(db_session)
        await ingest_pages_and_complete(
            db_session, scan_run.id, [make_axe_payload(violations=[make_violation("r1", "serious")])]
        )

        snapshot = await compute_app_score(db_session, scan_run)

        assert snapshot.score == approx(0.4)
        assert snapshot.total_pages == 1
        result = await db_session.execute(select(PageResult).where(PageResult.scan_run_id == scan_run.id))
        assert result.scalar_one().page_health == PageHealth.SERIOUS


class TestScoreIndependentOfPageHealth:
    async def test_score_correct_when_page_health_preset_to_wrong_value(self, db_session: AsyncSession) -> None:
        scan_run = await make_scan_run_with_parents(db_session)
        await ingest_pages_and_complete(
            db_session, scan_run.id, [make_axe_payload(violations=[make_violation("r1", "critical")])]
        )
        result = await db_session.execute(select(PageResult).where(PageResult.scan_run_id == scan_run.id))
        page = result.scalar_one()
        page.page_health = PageHealth.GOOD
        await db_session.flush()

        snapshot = await compute_app_score(db_session, scan_run)

        assert snapshot.score == approx(0.0)
        assert snapshot.pages_with_critical_violations == 1
        assert page.page_health == PageHealth.CRITICAL
