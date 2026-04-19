from datetime import UTC, datetime

import pytest
from pytest import approx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.enums import Impact, PageHealth, ScanRunStatus
from a11y_health.models.page_result import PageResult
from a11y_health.models.score_snapshot import ScoreSnapshot
from a11y_health.schemas.axe_payload import AxePayload
from a11y_health.services import app as app_service
from a11y_health.services.page_result import create_page_result
from a11y_health.services.scan_run import get_scan_run
from a11y_health.services.score import (
    build_snapshot,
    compute_app_score,
    compute_app_score_result,
    compute_page_health,
    rollup_brand_scores,
    rollup_org_unit_scores,
)
from tests.factories import (
    latest_brand_snapshot,
    latest_ou_snapshot,
    make_app,
    make_axe_payload,
    make_brand,
    make_org_unit,
    make_scan_run,
    make_scan_run_with_parents,
    make_violation,
    parse_axe_payload,
)


async def _ingest_and_score(db_session: AsyncSession, scan_run_id: int, payloads: list[dict]) -> ScoreSnapshot:
    for raw in payloads:
        await create_page_result(db_session, scan_run_id, AxePayload.model_validate(raw), raw)
    sr = await get_scan_run(db_session, scan_run_id)
    sr.status = ScanRunStatus.COMPLETED
    await db_session.flush()
    return await compute_app_score(db_session, sr)


async def _setup_and_score(db_session: AsyncSession, *payloads: dict) -> tuple[list[PageResult], ScoreSnapshot]:
    scan_run = await make_scan_run_with_parents(db_session)
    snapshot = await _ingest_and_score(db_session, scan_run.id, list(payloads))

    result = await db_session.execute(select(PageResult).where(PageResult.scan_run_id == scan_run.id))
    return list(result.scalars().all()), snapshot


_SNAPSHOT_AT = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)


def _snapshot(
    *,
    app_id: int | None = None,
    scan_run_id: int | None = None,
    org_unit_id: int | None = None,
    brand_id: int | None = None,
) -> ScoreSnapshot:
    return build_snapshot(
        score=0.8,
        total_violations=5,
        total_pages=10,
        pages_with_violations=2,
        pages_with_critical_violations=1,
        snapshot_at=_SNAPSHOT_AT,
        app_id=app_id,
        scan_run_id=scan_run_id,
        org_unit_id=org_unit_id,
        brand_id=brand_id,
    )


class TestBuildSnapshotOwnership:
    def test_rejects_no_owner(self) -> None:
        with pytest.raises(ValueError):
            _snapshot()

    def test_rejects_multiple_owners(self) -> None:
        with pytest.raises(ValueError):
            _snapshot(app_id=1, brand_id=2)

    def test_rejects_scan_run_without_app(self) -> None:
        with pytest.raises(ValueError):
            _snapshot(org_unit_id=1, scan_run_id=99)

    def test_accepts_app_without_scan_run(self) -> None:
        snapshot = _snapshot(app_id=1)
        assert snapshot.app_id == 1
        assert snapshot.scan_run_id is None


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
        assert result.score == approx(1.0)
        assert result.page_healths == {1: PageHealth.GOOD, 2: PageHealth.GOOD, 3: PageHealth.GOOD}

    def test_all_critical_pages_score_0(self) -> None:
        result = compute_app_score_result(
            page_ids=[1, 2],
            violations_by_page={1: [Impact.CRITICAL], 2: [Impact.CRITICAL]},
        )
        assert result.score == approx(0.0)

    def test_mixed_pages_weighted_average(self) -> None:
        result = compute_app_score_result(
            page_ids=[1, 2, 3, 4],
            violations_by_page={
                1: [Impact.CRITICAL],
                2: [Impact.SERIOUS],
                3: [Impact.MODERATE],
            },
        )
        assert result.score == approx(0.55)
        assert result.page_healths[4] == PageHealth.GOOD

    def test_zero_pages_returns_zero_score(self) -> None:
        result = compute_app_score_result(page_ids=[], violations_by_page={})
        assert result.score == approx(0.0)
        assert result.total_pages == 0

    def test_metric_accumulation(self) -> None:
        result = compute_app_score_result(
            page_ids=[1, 2, 3],
            violations_by_page={
                1: [Impact.CRITICAL, Impact.SERIOUS],
                3: [Impact.SERIOUS],
            },
        )
        assert result.total_violations == 3
        assert result.total_pages == 3
        assert result.pages_with_violations == 2
        assert result.pages_with_critical_violations == 1
        assert result.page_healths[1] == PageHealth.CRITICAL
        assert result.page_healths[2] == PageHealth.GOOD
        assert result.page_healths[3] == PageHealth.SERIOUS


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
        assert snapshot.total_violations == 3
        assert snapshot.pages_with_violations == 2
        assert snapshot.pages_with_critical_violations == 1
        assert snapshot.total_pages == 3
        assert snapshot.avg_violations_per_page == approx(1.0)
        assert snapshot.pct_pages_with_violations == approx(2 / 3)
        assert snapshot.pct_pages_with_critical_violations == approx(1 / 3)


class TestComputeAppScoreCreatesSnapshot:
    async def test_creates_snapshot_with_correct_metrics(self, db_session: AsyncSession) -> None:
        scan_run = await make_scan_run_with_parents(db_session)
        parsed, raw = parse_axe_payload(violations=[make_violation("r1", "serious")])
        await create_page_result(db_session, scan_run.id, parsed, raw)
        scan_run.status = ScanRunStatus.COMPLETED
        await db_session.flush()

        snapshot = await compute_app_score(db_session, scan_run)

        assert snapshot.score == approx(0.4)
        assert snapshot.total_pages == 1

        page_result = await db_session.execute(select(PageResult).where(PageResult.scan_run_id == scan_run.id))
        page = page_result.scalar_one()
        assert page.page_health == PageHealth.SERIOUS


class TestScoreIndependentOfPageHealth:
    async def test_score_correct_when_page_health_preset_to_wrong_value(self, db_session: AsyncSession) -> None:
        scan_run = await make_scan_run_with_parents(db_session)
        parsed, raw = parse_axe_payload(violations=[make_violation("r1", "critical")])
        await create_page_result(db_session, scan_run.id, parsed, raw)

        result = await db_session.execute(select(PageResult).where(PageResult.scan_run_id == scan_run.id))
        page = result.scalar_one()
        page.page_health = PageHealth.GOOD
        await db_session.flush()

        sr = await get_scan_run(db_session, scan_run.id)
        sr.status = ScanRunStatus.COMPLETED
        await db_session.flush()
        snapshot = await compute_app_score(db_session, sr)

        assert snapshot.score == approx(0.0)
        assert snapshot.pages_with_critical_violations == 1
        assert page.page_health == PageHealth.CRITICAL


async def _complete_and_score(
    db_session: AsyncSession,
    app_id: int,
    payloads: list[dict],
    scanned_at: datetime | None = None,
) -> ScoreSnapshot:
    sr = await make_scan_run(db_session, app_id=app_id, scanned_at=scanned_at)
    snapshot = await _ingest_and_score(db_session, sr.id, payloads)
    app = await app_service.get_app(db_session, app_id)
    await rollup_org_unit_scores(db_session, app.org_unit_id, snapshot.snapshot_at)
    return snapshot


class TestScoreModuleImports:
    def test_score_module_does_not_import_service_modules(self) -> None:
        import inspect

        import a11y_health.services.score as score_module

        source = inspect.getsource(score_module)
        assert "from a11y_health.services import app" not in source
        assert "from a11y_health.services import brand" not in source
        assert "from a11y_health.services import org_unit" not in source


class TestDecoupledImports:
    def test_org_unit_module_does_not_import_score(self) -> None:
        import inspect

        import a11y_health.services.org_unit as org_unit_module

        source = inspect.getsource(org_unit_module)
        assert "from a11y_health.services.score" not in source
        assert "import a11y_health.services.score" not in source

    def test_scan_run_module_does_not_import_score(self) -> None:
        import inspect

        import a11y_health.services.scan_run as scan_run_module

        source = inspect.getsource(scan_run_module)
        assert "from a11y_health.services.score" not in source
        assert "import a11y_health.services.score" not in source


class TestOrgUnitRollup:
    async def test_single_app_rollup_matches_app_snapshot(self, db_session: AsyncSession) -> None:
        org_unit = await make_org_unit(db_session, name="Parent Org")
        app = await make_app(db_session, name="App A", slug="app-a", org_unit_id=org_unit.id)
        app_snapshot = await _complete_and_score(
            db_session, app.id, [make_axe_payload(violations=[make_violation("r1", "serious")])]
        )

        ou_snapshot = await latest_ou_snapshot(db_session, org_unit.id)
        assert ou_snapshot.score == approx(app_snapshot.score)
        assert ou_snapshot.total_violations == app_snapshot.total_violations
        assert ou_snapshot.total_pages == app_snapshot.total_pages
        assert ou_snapshot.pages_with_violations == app_snapshot.pages_with_violations
        assert ou_snapshot.pages_with_critical_violations == app_snapshot.pages_with_critical_violations
        assert ou_snapshot.avg_violations_per_page == approx(app_snapshot.avg_violations_per_page)
        assert ou_snapshot.pct_pages_with_violations == approx(app_snapshot.pct_pages_with_violations)
        assert ou_snapshot.pct_pages_with_critical_violations == approx(app_snapshot.pct_pages_with_critical_violations)

    async def test_two_apps_rollup_averages_scores_sums_counts(self, db_session: AsyncSession) -> None:
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

        ou_snapshot = await latest_ou_snapshot(db_session, org_unit.id)

        assert ou_snapshot.score == approx(0.7)
        assert ou_snapshot.total_violations == 1
        assert ou_snapshot.total_pages == 2
        assert ou_snapshot.pages_with_violations == 1
        assert ou_snapshot.pages_with_critical_violations == 0
        assert ou_snapshot.avg_violations_per_page == approx(0.5)
        assert ou_snapshot.pct_pages_with_violations == approx(0.5)
        assert ou_snapshot.pct_pages_with_critical_violations == approx(0.0)

    async def test_multi_level_tree_cascades_to_root(self, db_session: AsyncSession) -> None:
        root = await make_org_unit(db_session, name="Root")
        middle = await make_org_unit(db_session, name="Middle", parent_id=root.id)
        leaf = await make_org_unit(db_session, name="Leaf", parent_id=middle.id)
        app = await make_app(db_session, name="App", slug="app-leaf", org_unit_id=leaf.id)

        app_snapshot = await _complete_and_score(
            db_session, app.id, [make_axe_payload(violations=[make_violation("r1", "serious")])]
        )

        for ou in [leaf, middle, root]:
            ou_snap = await latest_ou_snapshot(db_session, ou.id)
            assert ou_snap.score == approx(app_snapshot.score)
            assert ou_snap.total_violations == app_snapshot.total_violations
            assert ou_snap.total_pages == app_snapshot.total_pages

    async def test_mixed_children_org_units_and_apps(self, db_session: AsyncSession) -> None:
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

        assert (await latest_ou_snapshot(db_session, child_ou.id)).score == approx(1.0)

        parent_snap = await latest_ou_snapshot(db_session, parent.id)
        assert parent_snap.score == approx(0.5)
        assert parent_snap.total_violations == 1
        assert parent_snap.total_pages == 2
        assert parent_snap.pages_with_critical_violations == 1

    async def test_only_latest_app_snapshot_counts(self, db_session: AsyncSession) -> None:
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

        assert (await latest_ou_snapshot(db_session, org_unit.id)).score == approx(1.0)


async def _complete_score_and_rollup_brand(
    db_session: AsyncSession,
    app_id: int,
    brand_id: int,
    payloads: list[dict],
    scanned_at: datetime | None = None,
) -> ScoreSnapshot:
    sr = await make_scan_run(db_session, app_id=app_id, scanned_at=scanned_at)
    snapshot = await _ingest_and_score(db_session, sr.id, payloads)
    await rollup_brand_scores(db_session, brand_id, snapshot.snapshot_at)
    return snapshot


class TestBrandRollup:
    async def test_single_app_rollup_matches_app_snapshot(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="Humana")
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(db_session, name="App A", slug="app-a", org_unit_id=org_unit.id, brand_id=brand.id)

        app_snapshot = await _complete_score_and_rollup_brand(
            db_session, app.id, brand.id, [make_axe_payload(violations=[make_violation("r1", "serious")])]
        )

        brand_snap = await latest_brand_snapshot(db_session, brand.id)
        assert brand_snap.score == approx(app_snapshot.score)
        assert brand_snap.total_violations == app_snapshot.total_violations
        assert brand_snap.total_pages == app_snapshot.total_pages
        assert brand_snap.pages_with_violations == app_snapshot.pages_with_violations
        assert brand_snap.pages_with_critical_violations == app_snapshot.pages_with_critical_violations
        assert brand_snap.avg_violations_per_page == approx(app_snapshot.avg_violations_per_page)
        assert brand_snap.pct_pages_with_violations == approx(app_snapshot.pct_pages_with_violations)
        assert brand_snap.pct_pages_with_critical_violations == approx(app_snapshot.pct_pages_with_critical_violations)

    async def test_two_apps_rollup_averages_scores_sums_counts(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="CenterWell")
        org_unit = await make_org_unit(db_session, name="Org")
        app_a = await make_app(db_session, name="App A", slug="app-a", org_unit_id=org_unit.id, brand_id=brand.id)
        app_b = await make_app(db_session, name="App B", slug="app-b", org_unit_id=org_unit.id, brand_id=brand.id)

        await _complete_score_and_rollup_brand(
            db_session,
            app_a.id,
            brand.id,
            [make_axe_payload(violations=[make_violation("r1", "serious")])],
            scanned_at=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
        )
        await _complete_score_and_rollup_brand(
            db_session,
            app_b.id,
            brand.id,
            [make_axe_payload(url="https://example.com/b")],
            scanned_at=datetime(2026, 4, 1, 13, 0, 0, tzinfo=UTC),
        )

        brand_snap = await latest_brand_snapshot(db_session, brand.id)
        assert brand_snap.score == approx(0.7)
        assert brand_snap.total_violations == 1
        assert brand_snap.total_pages == 2
        assert brand_snap.pages_with_violations == 1
        assert brand_snap.pages_with_critical_violations == 0
        assert brand_snap.avg_violations_per_page == approx(0.5)
        assert brand_snap.pct_pages_with_violations == approx(0.5)
        assert brand_snap.pct_pages_with_critical_violations == approx(0.0)

    async def test_apps_across_different_org_units(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="Go365")
        ou_a = await make_org_unit(db_session, name="Division A")
        ou_b = await make_org_unit(db_session, name="Division B")
        app_a = await make_app(db_session, name="App A", slug="app-a", org_unit_id=ou_a.id, brand_id=brand.id)
        app_b = await make_app(db_session, name="App B", slug="app-b", org_unit_id=ou_b.id, brand_id=brand.id)

        await _complete_score_and_rollup_brand(
            db_session,
            app_a.id,
            brand.id,
            [make_axe_payload(violations=[make_violation("r1", "critical")])],
            scanned_at=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
        )
        await _complete_score_and_rollup_brand(
            db_session,
            app_b.id,
            brand.id,
            [make_axe_payload(url="https://example.com/b")],
            scanned_at=datetime(2026, 4, 1, 13, 0, 0, tzinfo=UTC),
        )

        brand_snap = await latest_brand_snapshot(db_session, brand.id)
        assert brand_snap.score == approx(0.5)
        assert brand_snap.total_violations == 1
        assert brand_snap.total_pages == 2
        assert brand_snap.pages_with_critical_violations == 1

    async def test_only_latest_app_snapshot_counts(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="Humana")
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(db_session, name="App", slug="app-latest", org_unit_id=org_unit.id, brand_id=brand.id)

        await _complete_score_and_rollup_brand(
            db_session,
            app.id,
            brand.id,
            [make_axe_payload(violations=[make_violation("r1", "critical")])],
            scanned_at=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
        )
        await _complete_score_and_rollup_brand(
            db_session,
            app.id,
            brand.id,
            [make_axe_payload(url="https://example.com/b")],
            scanned_at=datetime(2026, 4, 1, 13, 0, 0, tzinfo=UTC),
        )

        assert (await latest_brand_snapshot(db_session, brand.id)).score == approx(1.0)

    async def test_no_apps_with_scores_skips_snapshot(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="CarePlus")
        org_unit = await make_org_unit(db_session, name="Org")
        await make_app(db_session, name="App", slug="app-no-scores", org_unit_id=org_unit.id, brand_id=brand.id)

        await rollup_brand_scores(db_session, brand.id, datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC))

        result = await db_session.execute(select(ScoreSnapshot).where(ScoreSnapshot.brand_id == brand.id))
        assert result.scalar_one_or_none() is None
