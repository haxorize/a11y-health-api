from fastapi import APIRouter, Query

from a11y_health.api.deps import DbSession
from a11y_health.schemas.brand import BrandRead
from a11y_health.schemas.score_snapshot import ScoreSnapshotRead
from a11y_health.services import brand as brand_service
from a11y_health.services import score as score_service

router = APIRouter(prefix="/brands", tags=["brands"])


@router.get("")
async def list_brands(db: DbSession) -> list[BrandRead]:
    brands = await brand_service.list_brands(db)
    return [BrandRead.model_validate(b) for b in brands]


@router.get("/{brand_id}")
async def get_brand(db: DbSession, brand_id: int) -> BrandRead:
    brand = await brand_service.get_brand(db, brand_id)
    return BrandRead.model_validate(brand)


@router.get("/{brand_id}/scores")
async def list_brand_scores(
    db: DbSession,
    brand_id: int,
    offset: int = 0,
    limit: int = Query(default=20, le=100),
) -> list[ScoreSnapshotRead]:
    snapshots = await score_service.list_brand_scores(db, brand_id, offset=offset, limit=limit)
    return [ScoreSnapshotRead.model_validate(s) for s in snapshots]
