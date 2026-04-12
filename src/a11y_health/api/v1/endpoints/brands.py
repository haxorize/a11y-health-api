from fastapi import APIRouter

from a11y_health.api.deps import DbSession
from a11y_health.schemas.brand import BrandRead
from a11y_health.services import brand as brand_service

router = APIRouter(prefix="/brands", tags=["brands"])


@router.get("")
async def list_brands(db: DbSession) -> list[BrandRead]:
    brands = await brand_service.list_brands(db)
    return [BrandRead.model_validate(b) for b in brands]


@router.get("/{brand_id}")
async def get_brand(db: DbSession, brand_id: int) -> BrandRead:
    brand = await brand_service.get_brand(db, brand_id)
    return BrandRead.model_validate(brand)
