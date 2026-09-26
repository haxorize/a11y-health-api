from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core import existence
from a11y_health.core.exceptions import EmptyScanRunError, InvalidStatusTransitionError
from a11y_health.core.pagination import DEFAULT_PAGE_SIZE, CursorPage, TotalledCursorPage, paginate
from a11y_health.models.app import App
from a11y_health.models.enums import FindingType, Impact, ScanRunStatus
from a11y_health.models.page_result import PageResult
from a11y_health.models.rule_finding import RuleFinding
from a11y_health.models.scan_run import ScanRun
from a11y_health.models.score_snapshot import ScoreSnapshot
from a11y_health.schemas.page_result import PageMetricsRead
from a11y_health.schemas.scan_run import ScanRunCreate, ScanRunStatusUpdate
from a11y_health.services import scoring_orchestration


async def create_scan_run(session: AsyncSession, app_id: int, data: ScanRunCreate) -> ScanRun:
    await existence.get_by_pk(session, App, app_id)
    scan_run = ScanRun(app_id=app_id, status=ScanRunStatus.PENDING, **data.model_dump())
    session.add(scan_run)
    await session.flush()
    # RETURNING reloads only server-generated columns, and Postgres normalizes
    # this caller-supplied one to UTC.
    await session.refresh(scan_run, attribute_names=["scanned_at"])
    return scan_run


async def get_scan_run(session: AsyncSession, scan_run_id: int) -> ScanRun:
    return await existence.get_by_pk(session, ScanRun, scan_run_id)


async def list_scan_runs(
    session: AsyncSession, app_id: int, *, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
) -> TotalledCursorPage[ScanRun]:
    await existence.get_by_pk(session, App, app_id)
    stmt = select(ScanRun).where(ScanRun.app_id == app_id)
    # Newest first at the source: the UI renders the Scan Run history table in
    # server order (ADR 0017).
    return await paginate(
        session,
        stmt,
        keyset=[ScanRun.scanned_at, ScanRun.id],
        cursor=cursor,
        limit=limit,
        descending=True,
        with_total=True,
    )


_VALID_TRANSITIONS: dict[ScanRunStatus, set[ScanRunStatus]] = {
    ScanRunStatus.PENDING: {ScanRunStatus.COMPLETED},
    ScanRunStatus.COMPLETED: set(),
}


async def update_scan_run_status(session: AsyncSession, scan_run_id: int, data: ScanRunStatusUpdate) -> ScanRun:
    scan_run = await get_scan_run(session, scan_run_id)
    if data.status not in _VALID_TRANSITIONS[scan_run.status]:
        raise InvalidStatusTransitionError(ScanRun, scan_run_id, scan_run.status, data.status)
    if data.status == ScanRunStatus.COMPLETED:
        # A Scan Run has one or more Page Results (DOMAIN.md): an empty run must
        # not complete — its snapshot would score "no data" as 0.0 and roll up.
        page_count = await session.scalar(
            select(func.count()).select_from(PageResult).where(PageResult.scan_run_id == scan_run_id)
        )
        if not page_count:
            raise EmptyScanRunError(scan_run_id)
    scan_run.status = data.status
    await session.flush()
    await session.refresh(scan_run)
    if data.status == ScanRunStatus.COMPLETED:
        await scoring_orchestration.on_scan_run_completed(session, scan_run)
    return scan_run


async def list_page_metrics(
    session: AsyncSession, scan_run_id: int, *, cursor: str | None = None, limit: int = DEFAULT_PAGE_SIZE
) -> CursorPage[PageMetricsRead]:
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
    )
    return await paginate(
        session,
        stmt,
        keyset=[PageResult.id],
        cursor=cursor,
        limit=limit,
        into=lambda r: PageMetricsRead(
            id=r.PageResult.id,
            url=r.PageResult.url,
            page_health=r.PageResult.page_health,
            violation_count=r.violation_count,
            critical_violation_count=r.critical_violation_count,
        ),
    )


async def get_scan_run_summary(session: AsyncSession, scan_run_id: int) -> ScoreSnapshot:
    await get_scan_run(session, scan_run_id)
    stmt = select(ScoreSnapshot).where(ScoreSnapshot.scan_run_id == scan_run_id)
    return await existence.get_by_query(session, ScoreSnapshot, stmt, scan_run_id)


async def delete_scan_run(session: AsyncSession, scan_run_id: int) -> None:
    scan_run = await get_scan_run(session, scan_run_id)
    app = await existence.get_by_pk(session, App, scan_run.app_id)
    await session.delete(scan_run)
    await session.flush()
    await scoring_orchestration.on_app_latest_snapshot_changed(session, app)
