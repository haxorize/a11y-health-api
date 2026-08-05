from typing import Annotated

from fastapi import APIRouter, Query

from a11y_health.api.deps import DbSession
from a11y_health.core.error_contract import ErrorCode, error_responses
from a11y_health.core.pagination import Page, PageParams
from a11y_health.models.enums import ScoreSnapshotOwnerType
from a11y_health.schemas.score_snapshot import ScoreSnapshotRead
from a11y_health.services import owner as owner_service

router = APIRouter(prefix="/scores", tags=["scores"])


@router.get("/latest", responses=error_responses(ErrorCode.NOT_FOUND, ErrorCode.INVALID_CURSOR))
async def list_latest_scores(
    db: DbSession,
    owner_type: ScoreSnapshotOwnerType,
    pagination: PageParams,
    owner_id: Annotated[list[int] | None, Query()] = None,
    brand_id: int | None = None,
    under_org_unit_id: int | None = None,
    direct_only: bool = False,
) -> Page[ScoreSnapshotRead]:
    page = await owner_service.list_latest_scores(
        db,
        owner_type,
        owner_id=owner_id,
        brand_id=brand_id,
        under_org_unit_id=under_org_unit_id,
        direct_only=direct_only,
        cursor=pagination.cursor,
        limit=pagination.limit,
    )
    return Page.from_cursor_page(page, ScoreSnapshotRead.model_validate)
