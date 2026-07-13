"""Score computation and rollups — the write side of scoring.

Turns a completed Scan Run's findings into a Page Health per page, an App Score,
and a Score Snapshot, then rolls those totals up to Org Units (hierarchical,
cascading) and Brands (flat). The reading/listing side lives in `score.py`;
the events that call in here live in `scoring_orchestration.py`.

See `docs/architecture.md` ("The scoring & rollup model") for the full walk-through.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import ColumnElement, delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core import existence, integrity
from a11y_health.core.exceptions import ConcurrentRollupError
from a11y_health.models.app import App
from a11y_health.models.brand import Brand
from a11y_health.models.enums import FindingType, Impact, PageHealth
from a11y_health.models.org_unit import OrgUnit
from a11y_health.models.page_result import PageResult
from a11y_health.models.rule_finding import RuleFinding
from a11y_health.models.scan_run import ScanRun
from a11y_health.models.score_snapshot import (
    UQ_SCORE_SNAPSHOT_BRAND_SNAPSHOT_AT,
    UQ_SCORE_SNAPSHOT_ORG_UNIT_SNAPSHOT_AT,
    ScoreSnapshot,
)
from a11y_health.services import _scoring_vocabulary as scoring_vocabulary
from a11y_health.services._latest_snapshot import select_latest_snapshots


def safe_ratio(numerator: float, denominator: int) -> float:
    return numerator / denominator if denominator > 0 else 0.0


@dataclass(frozen=True)
class AppScoreResult:
    page_healths: dict[int, PageHealth]
    score: float
    total_violations: int
    total_pages: int
    pages_with_violations: int
    pages_with_critical_violations: int


def compute_page_health(impacts: list[Impact]) -> PageHealth:
    if not impacts:
        return PageHealth.GOOD
    return min(
        (scoring_vocabulary.IMPACT_TO_PAGE_HEALTH[impact] for impact in impacts),
        key=lambda health: scoring_vocabulary.PAGE_HEALTH_RANK[health],
    )


def compute_app_score_result(page_ids: list[int], violations_by_page: dict[int, list[Impact]]) -> AppScoreResult:
    total_pages = len(page_ids)
    total_violations = 0
    pages_with_violations = 0
    pages_with_critical_violations = 0
    weighted_sum = 0.0
    page_healths: dict[int, PageHealth] = {}

    for page_id in page_ids:
        impacts = violations_by_page.get(page_id, [])
        health = compute_page_health(impacts)
        page_healths[page_id] = health
        weighted_sum += scoring_vocabulary.PAGE_HEALTH_WEIGHT[health]

        violation_count = len(impacts)
        total_violations += violation_count
        if violation_count > 0:
            pages_with_violations += 1
        if health == PageHealth.CRITICAL:
            pages_with_critical_violations += 1

    return AppScoreResult(
        page_healths=page_healths,
        score=safe_ratio(weighted_sum, total_pages),
        total_violations=total_violations,
        total_pages=total_pages,
        pages_with_violations=pages_with_violations,
        pages_with_critical_violations=pages_with_critical_violations,
    )


async def compute_app_score(session: AsyncSession, scan_run: ScanRun) -> ScoreSnapshot:
    result = await session.execute(select(PageResult).where(PageResult.scan_run_id == scan_run.id))
    pages = list(result.scalars().all())
    page_ids = [p.id for p in pages]

    violations_by_page: dict[int, list[Impact]] = defaultdict(list)
    if page_ids:
        findings_result = await session.execute(
            select(RuleFinding.page_result_id, RuleFinding.impact).where(
                RuleFinding.page_result_id.in_(page_ids),
                RuleFinding.type == FindingType.VIOLATION,
            )
        )
        for page_result_id, impact in findings_result.all():
            violations_by_page[page_result_id].append(impact)

    score_result = compute_app_score_result(page_ids, violations_by_page)

    for page in pages:
        page.page_health = score_result.page_healths[page.id]

    snapshot = build_snapshot(
        score=score_result.score,
        total_violations=score_result.total_violations,
        total_pages=score_result.total_pages,
        pages_with_violations=score_result.pages_with_violations,
        pages_with_critical_violations=score_result.pages_with_critical_violations,
        snapshot_at=scan_run.scanned_at,
        app_id=scan_run.app_id,
        scan_run_id=scan_run.id,
    )
    session.add(snapshot)
    await session.flush()

    return snapshot


def build_snapshot(
    *,
    score: float,
    total_violations: int,
    total_pages: int,
    pages_with_violations: int,
    pages_with_critical_violations: int,
    snapshot_at: datetime,
    app_id: int | None = None,
    scan_run_id: int | None = None,
    org_unit_id: int | None = None,
    brand_id: int | None = None,
) -> ScoreSnapshot:
    # guard only — raises unless exactly one owner id is set
    _owner_criterion(app_id=app_id, org_unit_id=org_unit_id, brand_id=brand_id)
    if scan_run_id is not None and app_id is None:
        raise ValueError("scan_run_id requires app_id")

    return ScoreSnapshot(
        app_id=app_id,
        scan_run_id=scan_run_id,
        org_unit_id=org_unit_id,
        brand_id=brand_id,
        score=score,
        total_violations=total_violations,
        total_pages=total_pages,
        pages_with_violations=pages_with_violations,
        pages_with_critical_violations=pages_with_critical_violations,
        snapshot_at=snapshot_at,
    )


async def _latest_child_snapshots(session: AsyncSession, org_unit_id: int) -> list[ScoreSnapshot]:
    app_child = select(ScoreSnapshot).join(App, ScoreSnapshot.app_id == App.id).where(App.org_unit_id == org_unit_id)
    ou_child = (
        select(ScoreSnapshot)
        .join(OrgUnit, ScoreSnapshot.org_unit_id == OrgUnit.id)
        .where(OrgUnit.parent_id == org_unit_id)
    )
    stmt = select_latest_snapshots(
        app_child.union_all(ou_child), partition_on=[ScoreSnapshot.app_id, ScoreSnapshot.org_unit_id]
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


def _owner_criterion(
    *, app_id: int | None = None, org_unit_id: int | None = None, brand_id: int | None = None
) -> ColumnElement[bool]:
    """The exactly-one-owner invariant, stated once: raises ValueError unless
    exactly one owner id is set, and returns that owner's `column == id` filter
    (callers guarding a write may discard it)."""
    owners = [
        (ScoreSnapshot.app_id, app_id),
        (ScoreSnapshot.org_unit_id, org_unit_id),
        (ScoreSnapshot.brand_id, brand_id),
    ]
    chosen = [(column, owner_id) for column, owner_id in owners if owner_id is not None]
    if len(chosen) != 1:
        raise ValueError("Exactly one of app_id, org_unit_id, brand_id must be set")
    column, owner_id = chosen[0]
    return column == owner_id


# Equality basis for the same-observation dedupe: every aggregate the snapshot
# carries. A column-set canary test pins the model so adding a column forces a
# decision on whether it joins this tuple. Deriving this from the mapper was
# tried and reverted (6b721f1): the deny-list it needs drifts silently, and the
# canary carries the drift-proofing instead.
def _aggregate_values(snapshot: ScoreSnapshot) -> tuple[float, int, int, int, int]:
    return (
        snapshot.score,
        snapshot.total_violations,
        snapshot.total_pages,
        snapshot.pages_with_violations,
        snapshot.pages_with_critical_violations,
    )


# The #98 indexes allow at most one match; the id-desc pick mirrors the Latest
# Score Snapshot tie-break as a belt for pre-enforcement databases.
async def _snapshot_recorded_at_observation(
    session: AsyncSession, owner: ColumnElement[bool], snapshot_at: datetime
) -> ScoreSnapshot | None:
    return (
        await session.execute(
            select(ScoreSnapshot)
            .where(owner, ScoreSnapshot.snapshot_at == snapshot_at)
            .order_by(ScoreSnapshot.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _aggregate_and_save(
    session: AsyncSession,
    children: list[ScoreSnapshot],
    *,
    org_unit_id: int | None = None,
    brand_id: int | None = None,
) -> None:
    owner = _owner_criterion(org_unit_id=org_unit_id, brand_id=brand_id)
    # score is the unweighted arithmetic mean of children's scores per DOMAIN.md.
    # Snapshots forward of the new max are orphaned — the data behind them is gone — so prune.
    snapshot_at = max(c.snapshot_at for c in children)
    await session.execute(delete(ScoreSnapshot).where(owner, ScoreSnapshot.snapshot_at > snapshot_at))
    # Float summation is order-sensitive and the latest-child query has no ORDER BY;
    # sort so recomputes are bitwise-reproducible and the no-change skip below holds.
    children = sorted(children, key=lambda c: c.id)
    count = len(children)
    snapshot = build_snapshot(
        score=sum(c.score for c in children) / count,
        total_violations=sum(c.total_violations for c in children),
        total_pages=sum(c.total_pages for c in children),
        pages_with_violations=sum(c.pages_with_violations for c in children),
        pages_with_critical_violations=sum(c.pages_with_critical_violations for c in children),
        snapshot_at=snapshot_at,
        org_unit_id=org_unit_id,
        brand_id=brand_id,
    )
    # One snapshot per distinct observation, not one per trigger (#95, ADR 0015).
    # A newer observation time always appends — even with unchanged values — so
    # the latest snapshot never claims an observation whose source data is gone.
    existing = await _snapshot_recorded_at_observation(session, owner, snapshot_at)
    if existing is not None:
        if _aggregate_values(existing) == _aggregate_values(snapshot):
            return
        await session.execute(delete(ScoreSnapshot).where(owner, ScoreSnapshot.snapshot_at == snapshot_at))
    # The unique indexes (#98) only decide races: a concurrent rollup landing
    # between the read above and this insert makes the flush a violation.
    if org_unit_id is not None:
        index, entity, owner_id = UQ_SCORE_SNAPSHOT_ORG_UNIT_SNAPSHOT_AT, OrgUnit, org_unit_id
    else:
        index, entity, owner_id = UQ_SCORE_SNAPSHOT_BRAND_SNAPSHOT_AT, Brand, brand_id
    async with integrity.guard(session, {index: ConcurrentRollupError(existence.ENTITY_LABELS[entity], owner_id)}):
        session.add(snapshot)


async def rollup_org_unit_scores(session: AsyncSession, org_unit_id: int) -> None:
    children = await _latest_child_snapshots(session, org_unit_id)
    if children:
        await _aggregate_and_save(session, children, org_unit_id=org_unit_id)
    else:
        await session.execute(delete(ScoreSnapshot).where(_owner_criterion(org_unit_id=org_unit_id)))

    org_unit = await existence.get_by_pk(session, OrgUnit, org_unit_id)
    if org_unit.parent_id is not None:
        await rollup_org_unit_scores(session, org_unit.parent_id)


async def _latest_brand_app_snapshots(session: AsyncSession, brand_id: int) -> list[ScoreSnapshot]:
    brand_apps = select(ScoreSnapshot).join(App, ScoreSnapshot.app_id == App.id).where(App.brand_id == brand_id)
    stmt = select_latest_snapshots(brand_apps, partition_on=[ScoreSnapshot.app_id])
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def rollup_brand_scores(session: AsyncSession, brand_id: int) -> None:
    children = await _latest_brand_app_snapshots(session, brand_id)
    if children:
        await _aggregate_and_save(session, children, brand_id=brand_id)
    else:
        await session.execute(delete(ScoreSnapshot).where(_owner_criterion(brand_id=brand_id)))
