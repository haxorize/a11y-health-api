from typing import Annotated

from fastapi import APIRouter, Query

from a11y_health.api.deps import DbSession
from a11y_health.core.pagination import Page
from a11y_health.schemas.app import AppCreate, AppRead, AppUpdate
from a11y_health.schemas.score_snapshot import ScoreSnapshotRead
from a11y_health.services import app as app_service
from a11y_health.services import score as score_service

router = APIRouter(prefix="/apps", tags=["apps"])


@router.post("", status_code=201)
async def create_app(db: DbSession, data: AppCreate) -> AppRead:
    app = await app_service.create_app(db, data)
    return AppRead.model_validate(app)


@router.get("")
async def list_apps(
    db: DbSession,
    brand_id: Annotated[list[int] | None, Query()] = None,
    org_unit_id: Annotated[list[int] | None, Query()] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[AppRead]:
    page = await app_service.list_apps(db, brand_id=brand_id, org_unit_id=org_unit_id, cursor=cursor, limit=limit)
    return Page.from_cursor_page(page, AppRead.model_validate)


@router.get("/slug/{slug}")
async def get_app_by_slug(db: DbSession, slug: str) -> AppRead:
    app = await app_service.get_app_by_slug(db, slug)
    return AppRead.model_validate(app)


@router.get("/{app_id}")
async def get_app(db: DbSession, app_id: int) -> AppRead:
    app = await app_service.get_app(db, app_id)
    return AppRead.model_validate(app)


@router.patch("/{app_id}")
async def update_app(db: DbSession, app_id: int, data: AppUpdate) -> AppRead:
    app = await app_service.update_app(db, app_id, data)
    return AppRead.model_validate(app)


@router.get("/{app_id}/scores")
async def list_app_scores(
    db: DbSession,
    app_id: int,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[ScoreSnapshotRead]:
    page = await score_service.list_app_scores(db, app_id, cursor=cursor, limit=limit)
    return Page.from_cursor_page(page, ScoreSnapshotRead.model_validate)


@router.delete("/{app_id}", status_code=204)
async def delete_app(db: DbSession, app_id: int) -> None:
    await app_service.delete_app(db, app_id)
