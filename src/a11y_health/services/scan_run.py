from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import InvalidStatusTransitionError, NotFoundError, ScanRunCompletedError
from a11y_health.models.scan_run import ScanRun, ScanRunStatus
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
        raise InvalidStatusTransitionError(_RESOURCE, scan_run_id, scan_run.status.value, data.status.value)
    scan_run.status = data.status
    await session.flush()
    await session.refresh(scan_run)
    return scan_run


def assert_scan_run_pending(scan_run: ScanRun) -> None:
    if scan_run.status == ScanRunStatus.COMPLETED:
        raise ScanRunCompletedError(scan_run.id)
