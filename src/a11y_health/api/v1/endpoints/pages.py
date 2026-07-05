from typing import Annotated, Any

from fastapi import APIRouter, Body

from a11y_health.api.deps import DbSession
from a11y_health.core.error_contract import ErrorCode, error_responses
from a11y_health.schemas.axe_payload import parse_axe_payload
from a11y_health.schemas.page_result import PageResultRead
from a11y_health.services import page_result as page_result_service

router = APIRouter(prefix="/scan-runs/{scan_run_id}/pages", tags=["pages"])


@router.post(
    "",
    status_code=201,
    responses=error_responses(ErrorCode.NOT_FOUND, ErrorCode.SCAN_RUN_COMPLETED, ErrorCode.INVALID_AXE_PAYLOAD),
)
async def create_page_result(
    db: DbSession,
    scan_run_id: int,
    raw_payload: Annotated[dict[str, Any], Body()],
) -> PageResultRead:
    payload = parse_axe_payload(raw_payload)
    page_result = await page_result_service.create_page_result(db, scan_run_id, payload, raw_payload)
    return PageResultRead.model_validate(page_result)
