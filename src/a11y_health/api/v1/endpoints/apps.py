from typing import Annotated

from fastapi import APIRouter, Query

from a11y_health.api.deps import DbSession
from a11y_health.core.error_contract import ErrorCode, error_responses
from a11y_health.core.pagination import OrderParam, Page, PageParams
from a11y_health.schemas.app import AppCreate, AppRead, AppUpdate
from a11y_health.schemas.score_snapshot import ScoreSnapshotRead
from a11y_health.services import app as app_service
from a11y_health.services import score as score_service

router = APIRouter(prefix="/apps", tags=["apps"])


@router.post("", status_code=201, responses=error_responses(ErrorCode.NOT_FOUND, ErrorCode.DUPLICATE_SLUG))
async def create_app(db: DbSession, data: AppCreate) -> AppRead:
    app = await app_service.create_app(db, data)
    return AppRead.model_validate(app)


@router.get("", responses=error_responses(ErrorCode.INVALID_CURSOR))
async def list_apps(
    db: DbSession,
    pagination: PageParams,
    brand_id: Annotated[list[int] | None, Query()] = None,
    org_unit_id: Annotated[list[int] | None, Query()] = None,
) -> Page[AppRead]:
    page = await app_service.list_apps(
        db, brand_id=brand_id, org_unit_id=org_unit_id, cursor=pagination.cursor, limit=pagination.limit
    )
    return Page.from_cursor_page(page, AppRead.model_validate)


@router.get("/slug/{slug}", responses=error_responses(ErrorCode.NOT_FOUND))
async def get_app_by_slug(db: DbSession, slug: str) -> AppRead:
    app = await app_service.get_app_by_slug(db, slug)
    return AppRead.model_validate(app)


@router.get("/{app_id}", responses=error_responses(ErrorCode.NOT_FOUND))
async def get_app(db: DbSession, app_id: int) -> AppRead:
    app = await app_service.get_app(db, app_id)
    return AppRead.model_validate(app)


@router.patch("/{app_id}", responses=error_responses(ErrorCode.NOT_FOUND))
async def update_app(db: DbSession, app_id: int, data: AppUpdate) -> AppRead:
    app = await app_service.update_app(db, app_id, data)
    return AppRead.model_validate(app)


@router.get("/{app_id}/scores", responses=error_responses(ErrorCode.NOT_FOUND, ErrorCode.INVALID_CURSOR))
async def list_app_scores(
    db: DbSession,
    app_id: int,
    pagination: PageParams,
    order: OrderParam,
) -> Page[ScoreSnapshotRead]:
    page = await score_service.list_app_scores(
        db, app_id, cursor=pagination.cursor, limit=pagination.limit, descending=order.descending
    )
    return Page.from_cursor_page(page, ScoreSnapshotRead.model_validate)


@router.delete("/{app_id}", status_code=204, responses=error_responses(ErrorCode.NOT_FOUND))
async def delete_app(db: DbSession, app_id: int) -> None:
    await app_service.delete_app(db, app_id)
