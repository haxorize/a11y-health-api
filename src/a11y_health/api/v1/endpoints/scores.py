from fastapi import APIRouter

from a11y_health.api.deps import DbSession
from a11y_health.core.error_contract import ErrorCode, error_responses
from a11y_health.core.pagination import Page, PageParams
from a11y_health.models.enums import ScoreSnapshotOwnerType
from a11y_health.schemas.score_snapshot import ScoreSnapshotRead
from a11y_health.services import score as score_service

router = APIRouter(prefix="/scores", tags=["scores"])


@router.get("/latest", responses=error_responses(ErrorCode.INVALID_CURSOR))
async def list_latest_scores(
    db: DbSession,
    owner_type: ScoreSnapshotOwnerType,
    pagination: PageParams,
) -> Page[ScoreSnapshotRead]:
    page = await score_service.list_latest_scores(db, owner_type, cursor=pagination.cursor, limit=pagination.limit)
    return Page.from_cursor_page(page, ScoreSnapshotRead.model_validate)
