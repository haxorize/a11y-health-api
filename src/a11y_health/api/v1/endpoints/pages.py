from typing import Any

from fastapi import APIRouter, Body
from pydantic import ValidationError

from a11y_health.api.deps import DbSession
from a11y_health.core.exceptions import InvalidAxePayloadError
from a11y_health.schemas.axe_payload import AxePayload
from a11y_health.schemas.page_result import PageResultRead
from a11y_health.services import page_result as page_result_service

router = APIRouter(prefix="/scan-runs/{scan_run_id}/pages", tags=["pages"])


@router.post("", status_code=201)
async def create_page_result(
    db: DbSession,
    scan_run_id: int,
    raw_payload: dict[str, Any] = Body(...),  # noqa: B008
) -> PageResultRead:
    try:
        payload = AxePayload.model_validate(raw_payload)
    except ValidationError as exc:
        err = exc.errors()[0]
        loc = " → ".join(str(part) for part in err["loc"])
        raise InvalidAxePayloadError(f"{loc}: {err['msg']}") from exc
    page_result = await page_result_service.create_page_result(db, scan_run_id, payload, raw_payload)
    return PageResultRead.model_validate(page_result)
