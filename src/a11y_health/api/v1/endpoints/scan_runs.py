from fastapi import APIRouter, Query

from a11y_health.api.deps import DbSession
from a11y_health.schemas.page_result import PageMetricsRead
from a11y_health.schemas.scan_run import ScanRunCreate, ScanRunRead, ScanRunStatusUpdate, ScanRunSummaryRead
from a11y_health.services import scan_run as scan_run_service

app_router = APIRouter(prefix="/apps/{app_id}/scan-runs", tags=["scan-runs"])
router = APIRouter(prefix="/scan-runs", tags=["scan-runs"])


@app_router.post("", status_code=201)
async def create_scan_run(db: DbSession, app_id: int, data: ScanRunCreate) -> ScanRunRead:
    scan_run = await scan_run_service.create_scan_run(db, app_id, data)
    return ScanRunRead.model_validate(scan_run)


@app_router.get("")
async def list_scan_runs(
    db: DbSession,
    app_id: int,
    offset: int = 0,
    limit: int = Query(default=20, le=100),
) -> list[ScanRunRead]:
    scan_runs = await scan_run_service.list_scan_runs(db, app_id, offset=offset, limit=limit)
    return [ScanRunRead.model_validate(r) for r in scan_runs]


@router.get("/{scan_run_id}")
async def get_scan_run(db: DbSession, scan_run_id: int) -> ScanRunRead:
    scan_run = await scan_run_service.get_scan_run(db, scan_run_id)
    return ScanRunRead.model_validate(scan_run)


@router.get("/{scan_run_id}/pages")
async def list_scan_run_pages(
    db: DbSession,
    scan_run_id: int,
    offset: int = 0,
    limit: int = Query(default=20, le=100),
) -> list[PageMetricsRead]:
    return await scan_run_service.list_page_metrics(db, scan_run_id, offset=offset, limit=limit)


@router.get("/{scan_run_id}/summary")
async def get_scan_run_summary(db: DbSession, scan_run_id: int) -> ScanRunSummaryRead:
    snapshot = await scan_run_service.get_scan_run_summary(db, scan_run_id)
    return ScanRunSummaryRead.model_validate(snapshot)


@router.delete("/{scan_run_id}", status_code=204)
async def delete_scan_run(db: DbSession, scan_run_id: int) -> None:
    await scan_run_service.delete_scan_run(db, scan_run_id)


@router.patch("/{scan_run_id}")
async def update_scan_run_status(db: DbSession, scan_run_id: int, data: ScanRunStatusUpdate) -> ScanRunRead:
    scan_run = await scan_run_service.update_scan_run_status(db, scan_run_id, data)
    return ScanRunRead.model_validate(scan_run)
