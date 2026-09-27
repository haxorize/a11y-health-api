from fastapi import APIRouter

from a11y_health.api.deps import DbSession
from a11y_health.core.error_contract import ErrorCode, error_responses
from a11y_health.core.pagination import PageParams, TotaledPage
from a11y_health.schemas.rule_finding import (
    FindingFilterOptionsRead,
    FindingFilterParams,
    RuleFindingDetail,
    RuleFindingRead,
)
from a11y_health.services import rule_finding as rule_finding_service

router = APIRouter(prefix="/scan-runs/{scan_run_id}/findings", tags=["findings"])


@router.get("", responses=error_responses(ErrorCode.NOT_FOUND, ErrorCode.INVALID_CURSOR))
async def list_findings(
    db: DbSession,
    scan_run_id: int,
    # Before pagination, so the filters keep their place ahead of cursor/limit
    # in the published parameter order.
    filters: FindingFilterParams,
    pagination: PageParams,
) -> TotaledPage[RuleFindingRead]:
    page = await rule_finding_service.list_findings(
        db,
        scan_run_id,
        filters=filters,
        cursor=pagination.cursor,
        limit=pagination.limit,
    )
    return TotaledPage.from_totaled_cursor_page(page)


# Registered before /{finding_id} so the static segment isn't parsed as a
# finding id.
@router.get("/filter-options", responses=error_responses(ErrorCode.NOT_FOUND))
async def list_finding_filter_options(db: DbSession, scan_run_id: int) -> FindingFilterOptionsRead:
    return await rule_finding_service.list_filter_options(db, scan_run_id)


@router.get("/{finding_id}", responses=error_responses(ErrorCode.NOT_FOUND))
async def get_finding(
    db: DbSession,
    scan_run_id: int,
    finding_id: int,
) -> RuleFindingDetail:
    return await rule_finding_service.get_finding(db, scan_run_id, finding_id)
