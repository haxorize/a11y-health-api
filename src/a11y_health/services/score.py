from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.app import App
from a11y_health.models.enums import FindingType, Impact, PageHealth
from a11y_health.models.org_unit import OrgUnit
from a11y_health.models.page_result import PageResult
from a11y_health.models.rule_finding import RuleFinding
from a11y_health.models.scan_run import ScanRun
from a11y_health.models.score_snapshot import ScoreSnapshot

_IMPACT_TO_PAGE_HEALTH: dict[Impact, PageHealth] = {
    Impact.CRITICAL: PageHealth.CRITICAL,
    Impact.SERIOUS: PageHealth.SERIOUS,
    Impact.MODERATE: PageHealth.FAIR,
}

_PAGE_HEALTH_SEVERITY: dict[PageHealth, int] = {
    PageHealth.CRITICAL: 0,
    PageHealth.SERIOUS: 1,
    PageHealth.FAIR: 2,
    PageHealth.GOOD: 3,
}

_PAGE_HEALTH_WEIGHT: dict[PageHealth, float] = {
    PageHealth.CRITICAL: 0.0,
    PageHealth.SERIOUS: 0.4,
    PageHealth.FAIR: 0.8,
    PageHealth.GOOD: 1.0,
}


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
    worst = PageHealth.GOOD
    for impact in impacts:
        health = _IMPACT_TO_PAGE_HEALTH.get(impact)
        if health is None:
            continue
        if _PAGE_HEALTH_SEVERITY[health] < _PAGE_HEALTH_SEVERITY[worst]:
            worst = health
            if worst == PageHealth.CRITICAL:
                break
    return worst


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
        weighted_sum += _PAGE_HEALTH_WEIGHT[health]

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


async def _list_scores(
    session: AsyncSession,
    filter_col: Any,
    filter_val: int,
    *,
    offset: int = 0,
    limit: int = 20,
) -> Sequence[ScoreSnapshot]:
    result = await session.execute(
        select(ScoreSnapshot)
        .where(filter_col == filter_val)
        .order_by(ScoreSnapshot.snapshot_at, ScoreSnapshot.id)
        .offset(offset)
        .limit(limit)
    )
    return result.scalars().all()


async def list_app_scores(
    session: AsyncSession, app_id: int, *, offset: int = 0, limit: int = 20
) -> Sequence[ScoreSnapshot]:
    from a11y_health.services.app import get_app

    await get_app(session, app_id)
    return await _list_scores(session, ScoreSnapshot.app_id, app_id, offset=offset, limit=limit)


async def list_brand_scores(
    session: AsyncSession, brand_id: int, *, offset: int = 0, limit: int = 20
) -> Sequence[ScoreSnapshot]:
    from a11y_health.services.brand import get_brand

    await get_brand(session, brand_id)
    return await _list_scores(session, ScoreSnapshot.brand_id, brand_id, offset=offset, limit=limit)


async def list_org_unit_scores(
    session: AsyncSession, org_unit_id: int, *, offset: int = 0, limit: int = 20
) -> Sequence[ScoreSnapshot]:
    from a11y_health.services.org_unit import get_org_unit

    await get_org_unit(session, org_unit_id)
    return await _list_scores(session, ScoreSnapshot.org_unit_id, org_unit_id, offset=offset, limit=limit)


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
    owners = [id for id in (app_id, org_unit_id, brand_id) if id is not None]
    if len(owners) != 1:
        raise ValueError("Exactly one of app_id, org_unit_id, brand_id must be set")
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
        avg_violations_per_page=safe_ratio(total_violations, total_pages),
        pct_pages_with_violations=safe_ratio(pages_with_violations, total_pages),
        pct_pages_with_critical_violations=safe_ratio(pages_with_critical_violations, total_pages),
        snapshot_at=snapshot_at,
    )


async def _latest_snapshots_by_partition(
    session: AsyncSession,
    partition_col: Any,
    join_target: Any,
    join_cond: Any,
    filter_col: Any,
    filter_val: int,
) -> list[ScoreSnapshot]:
    row_num = (
        func.row_number()
        .over(partition_by=partition_col, order_by=(ScoreSnapshot.snapshot_at.desc(), ScoreSnapshot.id.desc()))
        .label("rn")
    )
    subq = (select(ScoreSnapshot.id, row_num).join(join_target, join_cond).where(filter_col == filter_val)).subquery()
    result = await session.execute(
        select(ScoreSnapshot).join(subq, ScoreSnapshot.id == subq.c.id).where(subq.c.rn == 1)
    )
    return list(result.scalars().all())


async def _latest_child_snapshots(session: AsyncSession, org_unit_id: int) -> list[ScoreSnapshot]:
    app_snapshots = await _latest_snapshots_by_partition(
        session, ScoreSnapshot.app_id, App, ScoreSnapshot.app_id == App.id, App.org_unit_id, org_unit_id
    )
    ou_snapshots = await _latest_snapshots_by_partition(
        session,
        ScoreSnapshot.org_unit_id,
        OrgUnit,
        ScoreSnapshot.org_unit_id == OrgUnit.id,
        OrgUnit.parent_id,
        org_unit_id,
    )
    return app_snapshots + ou_snapshots


async def _aggregate_and_save(
    session: AsyncSession,
    children: list[ScoreSnapshot],
    snapshot_at: datetime,
    *,
    org_unit_id: int | None = None,
    brand_id: int | None = None,
) -> None:
    # score is the unweighted arithmetic mean of children's scores per UBIQUITOUS_LANGUAGE.md;
    # the pct_* / avg_* fields are recomputed from summed totals, so the two lenses can diverge.
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
    session.add(snapshot)
    await session.flush()


async def rollup_org_unit_scores(session: AsyncSession, org_unit_id: int, snapshot_at: datetime) -> None:
    from a11y_health.services.org_unit import get_org_unit

    children = await _latest_child_snapshots(session, org_unit_id)
    if children:
        await _aggregate_and_save(session, children, snapshot_at, org_unit_id=org_unit_id)
    else:
        await session.execute(delete(ScoreSnapshot).where(ScoreSnapshot.org_unit_id == org_unit_id))

    org_unit = await get_org_unit(session, org_unit_id)
    if org_unit.parent_id is not None:
        await rollup_org_unit_scores(session, org_unit.parent_id, snapshot_at)


async def _latest_brand_app_snapshots(session: AsyncSession, brand_id: int) -> list[ScoreSnapshot]:
    return await _latest_snapshots_by_partition(
        session, ScoreSnapshot.app_id, App, ScoreSnapshot.app_id == App.id, App.brand_id, brand_id
    )


async def rollup_brand_scores(session: AsyncSession, brand_id: int, snapshot_at: datetime) -> None:
    children = await _latest_brand_app_snapshots(session, brand_id)
    if children:
        await _aggregate_and_save(session, children, snapshot_at, brand_id=brand_id)
    else:
        await session.execute(delete(ScoreSnapshot).where(ScoreSnapshot.brand_id == brand_id))
