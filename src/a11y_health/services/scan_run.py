from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import InvalidStatusTransitionError, NotFoundError, ScanRunCompletedError
from a11y_health.models.enums import FindingType, Impact, ScanRunStatus
from a11y_health.models.page_result import PageResult
from a11y_health.models.rule_finding import RuleFinding
from a11y_health.models.scan_run import ScanRun
from a11y_health.models.score_snapshot import ScoreSnapshot
from a11y_health.schemas.page_result import PageMetricsRead
from a11y_health.schemas.scan_run import ScanRunCreate, ScanRunStatusUpdate
from a11y_health.services.app import get_app

_RESOURCE = "Scan run"


async def create_scan_run(session: AsyncSession, app_id: int, data: ScanRunCreate) -> ScanRun:
    await get_app(session, app_id)
    scan_run = ScanRun(app_id=app_id, status=ScanRunStatus.PENDING, **data.model_dump())
    session.add(scan_run)
    await session.flush()
    await session.refresh(scan_run)
    return scan_run


async def get_scan_run(session: AsyncSession, scan_run_id: int) -> ScanRun:
    scan_run = await session.get(ScanRun, scan_run_id)
    if scan_run is None:
        raise NotFoundError(_RESOURCE, scan_run_id)
    return scan_run


async def list_scan_runs(session: AsyncSession, app_id: int, *, offset: int = 0, limit: int = 20) -> Sequence[ScanRun]:
    await get_app(session, app_id)
    stmt = select(ScanRun).where(ScanRun.app_id == app_id).order_by(ScanRun.id).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return result.scalars().all()


_VALID_TRANSITIONS: dict[ScanRunStatus, set[ScanRunStatus]] = {
    ScanRunStatus.PENDING: {ScanRunStatus.COMPLETED},
    ScanRunStatus.COMPLETED: set(),
}


async def update_scan_run_status(session: AsyncSession, scan_run_id: int, data: ScanRunStatusUpdate) -> ScanRun:
    scan_run = await get_scan_run(session, scan_run_id)
    if data.status not in _VALID_TRANSITIONS[scan_run.status]:
        raise InvalidStatusTransitionError(_RESOURCE, scan_run_id, scan_run.status, data.status)
    scan_run.status = data.status
    await session.flush()
    await session.refresh(scan_run)
    return scan_run


async def list_page_metrics(
    session: AsyncSession, scan_run_id: int, *, offset: int = 0, limit: int = 20
) -> list[PageMetricsRead]:
    await get_scan_run(session, scan_run_id)

    violation_count = (
        func.count(RuleFinding.id)
        .filter(
            RuleFinding.type == FindingType.VIOLATION,
        )
        .label("violation_count")
    )
    critical_count = (
        func.count(RuleFinding.id)
        .filter(
            RuleFinding.type == FindingType.VIOLATION,
            RuleFinding.impact == Impact.CRITICAL,
        )
        .label("critical_violation_count")
    )

    stmt = (
        select(PageResult, violation_count, critical_count)
        .outerjoin(RuleFinding, RuleFinding.page_result_id == PageResult.id)
        .where(PageResult.scan_run_id == scan_run_id)
        .group_by(PageResult.id)
        .order_by(PageResult.id)
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [
        PageMetricsRead(
            id=page.id,
            url=page.url,
            page_health=page.page_health,
            violation_count=violations,
            critical_violation_count=critical,
        )
        for page, violations, critical in result.all()
    ]


async def get_scan_run_summary(session: AsyncSession, scan_run_id: int) -> ScoreSnapshot:
    await get_scan_run(session, scan_run_id)
    result = await session.execute(select(ScoreSnapshot).where(ScoreSnapshot.scan_run_id == scan_run_id))
    snapshot = result.scalar_one_or_none()
    if snapshot is None:
        raise NotFoundError(f"{_RESOURCE} summary", scan_run_id)
    return snapshot


def assert_scan_run_pending(scan_run: ScanRun) -> None:
    if scan_run.status == ScanRunStatus.COMPLETED:
        raise ScanRunCompletedError(scan_run.id)
