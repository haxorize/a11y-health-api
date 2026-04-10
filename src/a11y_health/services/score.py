from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
    assert all(h is not None for h in page_healths)
    weighted_sum = sum(_PAGE_HEALTH_WEIGHT[h] for h in page_healths if h is not None)
    score = weighted_sum / total_pages if total_pages > 0 else 0.0

    snapshot = ScoreSnapshot(
        app_id=scan_run.app_id,
        scan_run_id=scan_run.id,
        score=score,
        total_issues=total_issues,
        pages_with_issues=pages_with_issues,
        pages_with_critical_issues=pages_with_critical_issues,
        total_pages=total_pages,
        avg_issues_per_page=total_issues / total_pages if total_pages > 0 else 0.0,
        pct_pages_with_issues=pages_with_issues / total_pages if total_pages > 0 else 0.0,
        pct_pages_with_critical_issues=pages_with_critical_issues / total_pages if total_pages > 0 else 0.0,
        snapshot_at=scan_run.scanned_at,
    )
    session.add(snapshot)
    await session.flush()
    return snapshot
