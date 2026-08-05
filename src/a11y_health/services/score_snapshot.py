"""App-score computation: a completed Scan Run's findings become a Page Health
per page, an App Score, and the App's Score Snapshot.

Everything per-owner — snapshot construction, rollups, score reads — lives in
`owner.py` (the Owner Dispatcher); the events that call in here live in
`scoring_orchestration.py`.

See `docs/architecture.md` ("The scoring & rollup model") for the full walk-through.
"""

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.enums import FindingType, Impact, PageHealth, ScoreSnapshotOwnerType
from a11y_health.models.page_result import PageResult
from a11y_health.models.rule_finding import RuleFinding
from a11y_health.models.scan_run import ScanRun
from a11y_health.models.score_snapshot import ScoreSnapshot
from a11y_health.services import owner, scoring_vocabulary


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

    snapshot = owner.owned(
        ScoreSnapshotOwnerType.APP,
        scan_run.app_id,
        scan_run_id=scan_run.id,
        score=score_result.score,
        total_violations=score_result.total_violations,
        total_pages=score_result.total_pages,
        pages_with_violations=score_result.pages_with_violations,
        pages_with_critical_violations=score_result.pages_with_critical_violations,
        snapshot_at=scan_run.scanned_at,
    )
    session.add(snapshot)
    await session.flush()

    return snapshot
