from typing import Any

from fastapi import APIRouter, Body

from a11y_health.api.deps import DbSession
from a11y_health.schemas.page_result import PageResultRead
from a11y_health.services import page_result as page_result_service

router = APIRouter(prefix="/scan-runs/{scan_run_id}/pages", tags=["pages"])


@router.post("", status_code=201)
async def create_page_result(
    db: DbSession,
    scan_run_id: int,
    payload: dict[str, Any] = Body(...),  # noqa: B008
) -> PageResultRead:
    page_result = await page_result_service.create_page_result(db, scan_run_id, payload)
    return PageResultRead.model_validate(page_result)
