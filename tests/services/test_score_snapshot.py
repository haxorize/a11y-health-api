import importlib
import inspect
from types import ModuleType

import pytest
from pytest import approx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.enums import Impact, PageHealth, ScanRunStatus
from a11y_health.models.page_result import PageResult
from a11y_health.models.score_snapshot import ScoreSnapshot
from a11y_health.services.page_result import create_page_result
from a11y_health.services.scan_run import get_scan_run
from a11y_health.services.score_snapshot import (
    compute_app_score,
    compute_app_score_result,
    compute_page_health,
)
from tests.factories import (
    ingest_and_score,
    make_axe_payload,
    make_scan_run_with_parents,
    make_violation,
)
from tests.import_graph import imported_modules


async def _setup_and_score(db_session: AsyncSession, *payloads: dict) -> tuple[list[PageResult], ScoreSnapshot]:
    scan_run = await make_scan_run_with_parents(db_session)
    snapshot = await ingest_and_score(db_session, scan_run.id, list(payloads))

    result = await db_session.execute(select(PageResult).where(PageResult.scan_run_id == scan_run.id))
    return list(result.scalars().all()), snapshot


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
    async def test_snapshot_stores_counts_and_score(self, db_session: AsyncSession) -> None:
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


class TestComputeAppScoreCreatesSnapshot:
    async def test_creates_snapshot_with_correct_metrics(self, db_session: AsyncSession) -> None:
        scan_run = await make_scan_run_with_parents(db_session)
        await create_page_result(
            db_session, scan_run.id, make_axe_payload(violations=[make_violation("r1", "serious")])
        )
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
        await create_page_result(
            db_session, scan_run.id, make_axe_payload(violations=[make_violation("r1", "critical")])
        )

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


def _sibling_service_imports(module: ModuleType) -> set[str]:
    # The shared walk sees every import spelling, including relative ones; this
    # rule is only the prefix filter over it.
    prefix = "a11y_health.services"
    imported = imported_modules(inspect.getsource(module), module.__name__)
    return {name.removeprefix(f"{prefix}.").split(".")[0] for name in imported if name.startswith(f"{prefix}.")}


class TestScoringModuleImports:
    # Entity fetches go through the Existence Guard, not a sibling service (see
    # architecture.md, "The Existence Guard and the two-tier call rule"): a
    # scoring module may cross the services namespace only for the shared
    # modules and the Owner Dispatcher named here — never a sibling resource
    # service. The rule is which shared modules a scoring module may reach, not
    # whether their names are private. Privacy is no help inside `services/`:
    # it is one flat package, so every module in it is a permitted importer of
    # `_latest_snapshot` and `_org_subtree` as far as test_import_honesty.py is
    # concerned. This allowlist is the only thing holding that line, and only
    # for the modules named below.
    @pytest.mark.parametrize(
        ("module_name", "shared_helpers"),
        [
            ("score_snapshot", {"scoring_vocabulary", "owner"}),
            ("owner", {"_latest_snapshot", "_org_subtree"}),
        ],
    )
    def test_module_imports_only_shared_helpers(self, module_name: str, shared_helpers: set[str]) -> None:
        module = importlib.import_module(f"a11y_health.services.{module_name}")

        assert _sibling_service_imports(module) <= shared_helpers


class TestDecoupledImports:
    def test_org_unit_module_does_not_import_score(self) -> None:
        import a11y_health.services.org_unit as org_unit_module

        assert not {"owner", "score_snapshot"} & _sibling_service_imports(org_unit_module)

    def test_scan_run_module_does_not_import_score(self) -> None:
        import a11y_health.services.scan_run as scan_run_module

        assert not {"owner", "score_snapshot"} & _sibling_service_imports(scan_run_module)
