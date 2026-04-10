from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.app import App
from a11y_health.models.org_unit import OrgUnit
from a11y_health.models.page_result import PageHealth, PageResult
from a11y_health.models.rule_finding import FindingType, Impact, RuleFinding
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


def _safe_ratio(numerator: float, denominator: int) -> float:
    return numerator / denominator if denominator > 0 else 0.0


def _worst_page_health(impacts: list[Impact]) -> PageHealth:
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


async def compute_scores(session: AsyncSession, scan_run: ScanRun) -> ScoreSnapshot:
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

    total_pages = len(pages)
    total_issues = 0
    pages_with_issues = 0
    pages_with_critical_issues = 0

    for page in pages:
        impacts = violations_by_page.get(page.id, [])
        page.page_health = _worst_page_health(impacts)

        violation_count = len(impacts)
        total_issues += violation_count
        if violation_count > 0:
            pages_with_issues += 1
        if page.page_health == PageHealth.CRITICAL:
            pages_with_critical_issues += 1

    page_healths = [p.page_health for p in pages]
    weighted_sum = sum(_PAGE_HEALTH_WEIGHT[h] for h in page_healths if h is not None)

    snapshot = ScoreSnapshot(
        app_id=scan_run.app_id,
        scan_run_id=scan_run.id,
        score=_safe_ratio(weighted_sum, total_pages),
        total_issues=total_issues,
        pages_with_issues=pages_with_issues,
        pages_with_critical_issues=pages_with_critical_issues,
        total_pages=total_pages,
        avg_issues_per_page=_safe_ratio(total_issues, total_pages),
        pct_pages_with_issues=_safe_ratio(pages_with_issues, total_pages),
        pct_pages_with_critical_issues=_safe_ratio(pages_with_critical_issues, total_pages),
        snapshot_at=scan_run.scanned_at,
    )
    session.add(snapshot)
    await session.flush()

    app = await session.get(App, scan_run.app_id)
    if app is not None:
        await rollup_org_unit_scores(session, app.org_unit_id, snapshot.snapshot_at)

    return snapshot


async def _latest_child_snapshots(session: AsyncSession, org_unit_id: int) -> list[ScoreSnapshot]:
    from sqlalchemy import func

    # Latest snapshot per direct child app (one query)
    app_max_subq = (
        select(func.max(ScoreSnapshot.snapshot_at))
        .join(App, ScoreSnapshot.app_id == App.id)
        .where(App.org_unit_id == org_unit_id)
        .group_by(ScoreSnapshot.app_id)
        .correlate(App)
    ).subquery()
    app_result = await session.execute(
        select(ScoreSnapshot)
        .join(App, ScoreSnapshot.app_id == App.id)
        .where(App.org_unit_id == org_unit_id, ScoreSnapshot.snapshot_at.in_(select(app_max_subq)))
    )
    snapshots = list(app_result.scalars().all())

    # Latest snapshot per direct child org unit (one query)
    ou_max_subq = (
        select(func.max(ScoreSnapshot.snapshot_at))
        .join(OrgUnit, ScoreSnapshot.org_unit_id == OrgUnit.id)
        .where(OrgUnit.parent_id == org_unit_id)
        .group_by(ScoreSnapshot.org_unit_id)
        .correlate(OrgUnit)
    ).subquery()
    ou_result = await session.execute(
        select(ScoreSnapshot)
        .join(OrgUnit, ScoreSnapshot.org_unit_id == OrgUnit.id)
        .where(OrgUnit.parent_id == org_unit_id, ScoreSnapshot.snapshot_at.in_(select(ou_max_subq)))
    )
    snapshots.extend(ou_result.scalars().all())

    return snapshots


async def rollup_org_unit_scores(
    session: AsyncSession, org_unit_id: int, snapshot_at: datetime, *, parent_id: int | None = None
) -> None:
    children = await _latest_child_snapshots(session, org_unit_id)
    if not children:
        return

    count = len(children)
    total_issues = sum(c.total_issues for c in children)
    total_pages = sum(c.total_pages for c in children)
    pages_with_issues = sum(c.pages_with_issues for c in children)
    pages_with_critical_issues = sum(c.pages_with_critical_issues for c in children)

    snapshot = ScoreSnapshot(
        org_unit_id=org_unit_id,
        score=sum(c.score for c in children) / count,
        total_issues=total_issues,
        total_pages=total_pages,
        pages_with_issues=pages_with_issues,
        pages_with_critical_issues=pages_with_critical_issues,
        avg_issues_per_page=_safe_ratio(total_issues, total_pages),
        pct_pages_with_issues=_safe_ratio(pages_with_issues, total_pages),
        pct_pages_with_critical_issues=_safe_ratio(pages_with_critical_issues, total_pages),
        snapshot_at=snapshot_at,
    )
    session.add(snapshot)
    await session.flush()

    if parent_id is None:
        org_unit = await session.get(OrgUnit, org_unit_id)
        parent_id = org_unit.parent_id if org_unit else None
    if parent_id is not None:
        await rollup_org_unit_scores(session, parent_id, snapshot_at)
