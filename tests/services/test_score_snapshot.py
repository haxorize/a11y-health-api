import ast
import importlib
import inspect
from datetime import UTC, datetime
from types import ModuleType

import pytest
from pytest import approx
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import ConcurrentRollupError
from a11y_health.models.enums import Impact, PageHealth, ScanRunStatus
from a11y_health.models.page_result import PageResult
from a11y_health.models.score_snapshot import (
    UQ_SCORE_SNAPSHOT_BRAND_SNAPSHOT_AT,
    UQ_SCORE_SNAPSHOT_ORG_UNIT_SNAPSHOT_AT,
    ScoreSnapshot,
)
from a11y_health.schemas.axe_payload import parse_axe_payload
from a11y_health.services import app as app_service
from a11y_health.services import score_snapshot as score_snapshot_service
from a11y_health.services.page_result import create_page_result
from a11y_health.services.scan_run import get_scan_run
from a11y_health.services.score_snapshot import (
    build_snapshot,
    compute_app_score,
    compute_app_score_result,
    compute_page_health,
    rollup_brand_scores,
    rollup_org_unit_scores,
)
from tests.factories import (
    brand_snapshots,
    latest_brand_snapshot,
    latest_ou_snapshot,
    make_app,
    make_app_with_org_unit,
    make_axe_payload,
    make_brand,
    make_org_unit,
    make_parsed_axe_payload,
    make_scan_run,
    make_scan_run_with_parents,
    make_score_snapshot,
    make_violation,
    ou_snapshots,
)


async def _ingest_and_score(db_session: AsyncSession, scan_run_id: int, payloads: list[dict]) -> ScoreSnapshot:
    for raw in payloads:
        await create_page_result(db_session, scan_run_id, parse_axe_payload(raw))
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


def test_score_snapshot_column_set_is_pinned() -> None:
    # Canary: a new column must decide whether it joins the same-observation
    # equality basis in _aggregate_values — update the tuple there, then here.
    assert {attr.key for attr in ScoreSnapshot.__mapper__.column_attrs} == {
        "id",
        "app_id",
        "scan_run_id",
        "org_unit_id",
        "brand_id",
        "score",
        "total_violations",
        "total_pages",
        "pages_with_violations",
        "pages_with_critical_violations",
        "snapshot_at",
        "created_at",
        "updated_at",
    }


def test_rollup_owner_snapshot_columns_are_build_snapshot_kwargs() -> None:
    # Canary: _apply_rollup passes **{spec.snapshot_column.key: owner_id} into
    # build_snapshot — a name coupling ty can't see. Pin it so renaming either
    # side fails here by name instead of as a TypeError mid-rollup.
    params = inspect.signature(score_snapshot_service.build_snapshot).parameters
    for spec in score_snapshot_service._ROLLUP_OWNERS.values():
        assert spec.snapshot_column.key in params


class TestComputeAppScoreCreatesSnapshot:
    async def test_creates_snapshot_with_correct_metrics(self, db_session: AsyncSession) -> None:
        scan_run = await make_scan_run_with_parents(db_session)
        parsed = make_parsed_axe_payload(violations=[make_violation("r1", "serious")])
        await create_page_result(db_session, scan_run.id, parsed)
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
        parsed = make_parsed_axe_payload(violations=[make_violation("r1", "critical")])
        await create_page_result(db_session, scan_run.id, parsed)

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
    await rollup_org_unit_scores(db_session, app.org_unit_id)
    return snapshot


def _sibling_service_imports(module: ModuleType) -> set[str]:
    # AST rather than source substrings: catches every import form and ignores
    # comments that merely mention the package path.
    prefix = "a11y_health.services"
    siblings: set[str] = set()
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        if isinstance(node, ast.Import):
            siblings.update(
                alias.name.removeprefix(f"{prefix}.").split(".")[0]
                for alias in node.names
                if alias.name.startswith(f"{prefix}.")
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == prefix:
                siblings.update(alias.name for alias in node.names)
            elif node.module.startswith(f"{prefix}."):
                siblings.add(node.module.removeprefix(f"{prefix}.").split(".")[0])
    return siblings


class TestScoringModuleImports:
    # Entity fetches go through the Existence Guard, not a sibling service (see
    # architecture.md, "The Existence Guard and the two-tier call rule"): a
    # scoring module may cross the services namespace only for the shared
    # underscore helpers named here — never a sibling resource service, and not
    # another service's private module just because its name starts with "_".
    @pytest.mark.parametrize(
        ("module_name", "shared_helpers"),
        [
            ("score", {"_latest_snapshot"}),
            ("score_snapshot", {"_scoring_vocabulary", "_latest_snapshot"}),
        ],
    )
    def test_module_imports_only_shared_helpers(self, module_name: str, shared_helpers: set[str]) -> None:
        module = importlib.import_module(f"a11y_health.services.{module_name}")

        assert _sibling_service_imports(module) <= shared_helpers


class TestDecoupledImports:
    def test_org_unit_module_does_not_import_score(self) -> None:
        import a11y_health.services.org_unit as org_unit_module

        assert not {"score", "score_snapshot"} & _sibling_service_imports(org_unit_module)

    def test_scan_run_module_does_not_import_score(self) -> None:
        import a11y_health.services.scan_run as scan_run_module

        assert not {"score", "score_snapshot"} & _sibling_service_imports(scan_run_module)


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

    async def test_child_app_and_org_unit_with_equal_ids_both_count(self, db_session: AsyncSession) -> None:
        # app.id and org_unit.id come from separate identity sequences, so a
        # child App and a child Org Unit can legitimately share an id value —
        # the latest-per-child partition must keep them apart.
        parent = await make_org_unit(db_session, name="Collide Parent")
        brand = await make_brand(db_session)
        collided_id = 900_000_001
        await db_session.execute(
            text(
                "INSERT INTO org_unit (id, name, parent_id) "
                "OVERRIDING SYSTEM VALUE VALUES (:id, 'Collide OU', :parent_id)"
            ),
            {"id": collided_id, "parent_id": parent.id},
        )
        await db_session.execute(
            text(
                "INSERT INTO app (id, name, slug, brand_id, org_unit_id) "
                "OVERRIDING SYSTEM VALUE VALUES (:id, 'Collide App', 'collide-app', :brand_id, :org_unit_id)"
            ),
            {"id": collided_id, "brand_id": brand.id, "org_unit_id": parent.id},
        )

        await make_score_snapshot(
            db_session, app_id=collided_id, score=0.4, snapshot_at=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
        )
        await make_score_snapshot(
            db_session, org_unit_id=collided_id, score=0.8, snapshot_at=datetime(2026, 4, 1, 13, 0, 0, tzinfo=UTC)
        )

        await rollup_org_unit_scores(db_session, parent.id)

        assert (await latest_ou_snapshot(db_session, parent.id)).score == approx((0.4 + 0.8) / 2)

    async def test_higher_id_wins_when_snapshot_at_ties(self, db_session: AsyncSession) -> None:
        org_unit = await make_org_unit(db_session, name="Tie Org")
        app = await make_app(db_session, name="Tie App", slug="app-tie", org_unit_id=org_unit.id)
        tied_at = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)

        await make_score_snapshot(db_session, app_id=app.id, score=0.2, snapshot_at=tied_at)
        await make_score_snapshot(db_session, app_id=app.id, score=0.8, snapshot_at=tied_at)

        await rollup_org_unit_scores(db_session, org_unit.id)

        assert (await latest_ou_snapshot(db_session, org_unit.id)).score == approx(0.8)


class TestRollupNoChangeRecompute:
    # History keeps one Score Snapshot per distinct observation, not one per trigger (#95).

    async def test_unchanged_recompute_records_nothing_new(self, db_session: AsyncSession) -> None:
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(db_session, name="App", slug="app-nochange", org_unit_id=org_unit.id)
        await _complete_and_score(db_session, app.id, [make_axe_payload(violations=[make_violation("r1", "serious")])])

        # deletion and reparent triggers re-run the rollup with unchanged children
        await rollup_org_unit_scores(db_session, org_unit.id)
        await rollup_org_unit_scores(db_session, org_unit.id)

        snapshots = await ou_snapshots(db_session, org_unit.id)
        assert len(snapshots) == 1
        assert snapshots[0].score == approx(0.4)

    async def test_changed_aggregate_at_same_observation_time_replaces(self, db_session: AsyncSession) -> None:
        scanned_at = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
        org_unit = await make_org_unit(db_session, name="Org")
        app_a = await make_app(db_session, name="App A", slug="app-a", org_unit_id=org_unit.id)
        app_b = await make_app(db_session, name="App B", slug="app-b", org_unit_id=org_unit.id)

        await _complete_and_score(
            db_session,
            app_a.id,
            [make_axe_payload(violations=[make_violation("r1", "serious")])],
            scanned_at=scanned_at,
        )
        await _complete_and_score(
            db_session,
            app_b.id,
            [make_axe_payload(url="https://example.com/b")],
            scanned_at=scanned_at,
        )

        snapshots = await ou_snapshots(db_session, org_unit.id)
        assert len(snapshots) == 1
        assert snapshots[0].score == approx(0.7)
        assert snapshots[0].snapshot_at == scanned_at

    async def test_older_scan_completion_reproducing_aggregate_records_nothing_new(
        self, db_session: AsyncSession
    ) -> None:
        # An older scan that doesn't displace the app's latest snapshot leaves the
        # aggregate — values and observation time — unchanged.
        latest_scanned_at = datetime(2026, 4, 2, 12, 0, 0, tzinfo=UTC)
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(db_session, name="App", slug="app-same-mean", org_unit_id=org_unit.id)

        await _complete_and_score(
            db_session,
            app.id,
            [make_axe_payload(violations=[make_violation("r1", "serious")])],
            scanned_at=latest_scanned_at,
        )
        await _complete_and_score(
            db_session,
            app.id,
            [make_axe_payload(violations=[make_violation("r1", "serious")])],
            scanned_at=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
        )

        snapshots = await ou_snapshots(db_session, org_unit.id)
        assert len(snapshots) == 1
        assert snapshots[0].snapshot_at == latest_scanned_at

    async def test_newer_observation_with_unchanged_values_appends(self, db_session: AsyncSession) -> None:
        # A distinct observation is history even when the value didn't move —
        # skipping it would leave the latest snapshot claiming an observation
        # time whose scan may later be deleted.
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(db_session, name="App", slug="app-flat-trend", org_unit_id=org_unit.id)

        await _complete_and_score(
            db_session,
            app.id,
            [make_axe_payload(violations=[make_violation("r1", "serious")])],
            scanned_at=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
        )
        second_scanned_at = datetime(2026, 4, 2, 12, 0, 0, tzinfo=UTC)
        await _complete_and_score(
            db_session,
            app.id,
            [make_axe_payload(violations=[make_violation("r1", "serious")])],
            scanned_at=second_scanned_at,
        )

        snapshots = await ou_snapshots(db_session, org_unit.id)
        assert len(snapshots) == 2
        assert snapshots[-1].snapshot_at == second_scanned_at

    async def test_brand_unchanged_recompute_records_nothing_new(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="Humana")
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(db_session, name="App", slug="app-brand", org_unit_id=org_unit.id, brand_id=brand.id)
        await _complete_score_and_rollup_brand(
            db_session, app.id, brand.id, [make_axe_payload(violations=[make_violation("r1", "serious")])]
        )

        await rollup_brand_scores(db_session, brand.id)
        await rollup_brand_scores(db_session, brand.id)

        snapshots = await brand_snapshots(db_session, brand.id)
        assert len(snapshots) == 1
        assert snapshots[0].score == approx(0.4)


async def _complete_score_and_rollup_brand(
    db_session: AsyncSession,
    app_id: int,
    brand_id: int,
    payloads: list[dict],
    scanned_at: datetime | None = None,
) -> ScoreSnapshot:
    sr = await make_scan_run(db_session, app_id=app_id, scanned_at=scanned_at)
    snapshot = await _ingest_and_score(db_session, sr.id, payloads)
    await rollup_brand_scores(db_session, brand_id)
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

    async def test_apps_across_different_org_units(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="Go365")
        top = await make_org_unit(db_session, name="Top")
        ou_a = await make_org_unit(db_session, name="Division A", parent_id=top.id)
        ou_b = await make_org_unit(db_session, name="Division B", parent_id=top.id)
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

        await rollup_brand_scores(db_session, brand.id)

        assert await brand_snapshots(db_session, brand.id) == []


def _bypass_dedupe_check_to_lose_the_race(mocker) -> None:
    # The race the constraint decides: the dedupe read saw nothing, but a
    # concurrent rollup's row lands before our write.
    mocker.patch.object(
        score_snapshot_service, "_snapshot_recorded_at_observation", new_callable=mocker.AsyncMock, return_value=None
    )


class TestRollupSnapshotUniqueness:
    async def test_schema_rejects_duplicate_org_unit_snapshot_at_one_observation_time(
        self, db_session: AsyncSession
    ) -> None:
        org_unit = await make_org_unit(db_session)
        await make_score_snapshot(db_session, org_unit_id=org_unit.id, snapshot_at=_SNAPSHOT_AT)
        db_session.add(_snapshot(org_unit_id=org_unit.id))
        with pytest.raises(IntegrityError, match=UQ_SCORE_SNAPSHOT_ORG_UNIT_SNAPSHOT_AT):
            await db_session.flush()

    async def test_schema_rejects_duplicate_brand_snapshot_at_one_observation_time(
        self, db_session: AsyncSession
    ) -> None:
        brand = await make_brand(db_session)
        await make_score_snapshot(db_session, brand_id=brand.id, snapshot_at=_SNAPSHOT_AT)
        db_session.add(_snapshot(brand_id=brand.id))
        with pytest.raises(IntegrityError, match=UQ_SCORE_SNAPSHOT_BRAND_SNAPSHOT_AT):
            await db_session.flush()

    async def test_app_snapshots_stay_unconstrained_per_observation_time(self, db_session: AsyncSession) -> None:
        # Two Scan Runs for one App may share scanned_at; latest selection breaks
        # the tie. Proven by the second flush not raising.
        app = await make_app_with_org_unit(db_session)
        first = await make_score_snapshot(db_session, app_id=app.id, snapshot_at=_SNAPSHOT_AT)
        second = await make_score_snapshot(db_session, app_id=app.id, snapshot_at=_SNAPSHOT_AT)
        assert first.id != second.id

    async def test_org_unit_rollup_losing_the_race_raises_concurrent_rollup_error(
        self, db_session: AsyncSession, mocker
    ) -> None:
        org_unit = await make_org_unit(db_session)
        app = await make_app(db_session, name="Race App", slug="race-app", org_unit_id=org_unit.id)
        await make_score_snapshot(db_session, app_id=app.id, snapshot_at=_SNAPSHOT_AT)
        # The winner's row: landed between our dedupe check and our write.
        await make_score_snapshot(db_session, org_unit_id=org_unit.id, snapshot_at=_SNAPSHOT_AT)
        _bypass_dedupe_check_to_lose_the_race(mocker)
        with pytest.raises(ConcurrentRollupError, match="Org unit.*updated by another request"):
            await rollup_org_unit_scores(db_session, org_unit.id)

    async def test_brand_rollup_losing_the_race_raises_concurrent_rollup_error(
        self, db_session: AsyncSession, mocker
    ) -> None:
        brand = await make_brand(db_session)
        app = await make_app_with_org_unit(db_session, brand_id=brand.id)
        await make_score_snapshot(db_session, app_id=app.id, snapshot_at=_SNAPSHOT_AT)
        await make_score_snapshot(db_session, brand_id=brand.id, snapshot_at=_SNAPSHOT_AT)
        _bypass_dedupe_check_to_lose_the_race(mocker)
        with pytest.raises(ConcurrentRollupError, match="Brand.*updated by another request"):
            await rollup_brand_scores(db_session, brand.id)
