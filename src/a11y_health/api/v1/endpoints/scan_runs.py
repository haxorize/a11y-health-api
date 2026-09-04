from typing import Annotated, Any

from fastapi import APIRouter, Body

from a11y_health.api.deps import DbSession
from a11y_health.core.error_contract import ErrorCode, error_responses
from a11y_health.core.pagination import Page, PageParams, TotalledPage
from a11y_health.schemas.page_result import PageMetricsRead, PageResultRead
from a11y_health.schemas.scan_run import ScanRunCreate, ScanRunRead, ScanRunStatusUpdate, ScanRunSummaryRead
from a11y_health.services import page_result as page_result_service
from a11y_health.services import scan_run as scan_run_service

app_router = APIRouter(prefix="/apps/{app_id}/scan-runs", tags=["scan-runs"])
router = APIRouter(prefix="/scan-runs", tags=["scan-runs"])
# The pages surface keeps its own tag so the whole /scan-runs/{id}/pages URL
# lives in this one module without changing the contract's tag grouping.
pages_router = APIRouter(prefix="/scan-runs/{scan_run_id}/pages", tags=["pages"])


@app_router.post("", status_code=201, responses=error_responses(ErrorCode.NOT_FOUND))
async def create_scan_run(db: DbSession, app_id: int, data: ScanRunCreate) -> ScanRunRead:
    scan_run = await scan_run_service.create_scan_run(db, app_id, data)
    return ScanRunRead.model_validate(scan_run)


@app_router.get("", responses=error_responses(ErrorCode.NOT_FOUND, ErrorCode.INVALID_CURSOR))
async def list_scan_runs(
    db: DbSession,
    app_id: int,
    pagination: PageParams,
) -> TotalledPage[ScanRunRead]:
    page = await scan_run_service.list_scan_runs(db, app_id, cursor=pagination.cursor, limit=pagination.limit)
    return TotalledPage.from_totalled_cursor_page(page, ScanRunRead.model_validate)


@router.get("/{scan_run_id}", responses=error_responses(ErrorCode.NOT_FOUND))
async def get_scan_run(db: DbSession, scan_run_id: int) -> ScanRunRead:
    scan_run = await scan_run_service.get_scan_run(db, scan_run_id)
    return ScanRunRead.model_validate(scan_run)


@router.get("/{scan_run_id}/pages", responses=error_responses(ErrorCode.NOT_FOUND, ErrorCode.INVALID_CURSOR))
async def list_scan_run_pages(
    db: DbSession,
    scan_run_id: int,
    pagination: PageParams,
) -> Page[PageMetricsRead]:
    page = await scan_run_service.list_page_metrics(db, scan_run_id, cursor=pagination.cursor, limit=pagination.limit)
    return Page.from_cursor_page(page)


@pages_router.post(
    "",
    status_code=201,
    responses=error_responses(ErrorCode.NOT_FOUND, ErrorCode.SCAN_RUN_COMPLETED, ErrorCode.INVALID_AXE_PAYLOAD),
)
async def create_page_result(
    db: DbSession,
    scan_run_id: int,
    raw_payload: Annotated[dict[str, Any], Body()],
) -> PageResultRead:
    page_result = await page_result_service.create_page_result(db, scan_run_id, raw_payload)
    return PageResultRead.model_validate(page_result)


@router.get("/{scan_run_id}/summary", responses=error_responses(ErrorCode.NOT_FOUND))
async def get_scan_run_summary(db: DbSession, scan_run_id: int) -> ScanRunSummaryRead:
    snapshot = await scan_run_service.get_scan_run_summary(db, scan_run_id)
    return ScanRunSummaryRead.model_validate(snapshot)


@router.delete(
    "/{scan_run_id}", status_code=204, responses=error_responses(ErrorCode.NOT_FOUND, ErrorCode.CONCURRENT_ROLLUP)
)
async def delete_scan_run(db: DbSession, scan_run_id: int) -> None:
    await scan_run_service.delete_scan_run(db, scan_run_id)


@router.patch(
    "/{scan_run_id}",
    responses=error_responses(
        ErrorCode.NOT_FOUND,
        ErrorCode.INVALID_STATUS_TRANSITION,
        ErrorCode.EMPTY_SCAN_RUN,
        ErrorCode.CONCURRENT_ROLLUP,
    ),
)
async def update_scan_run_status(db: DbSession, scan_run_id: int, data: ScanRunStatusUpdate) -> ScanRunRead:
    scan_run = await scan_run_service.update_scan_run_status(db, scan_run_id, data)
    return ScanRunRead.model_validate(scan_run)
