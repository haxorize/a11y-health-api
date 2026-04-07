from fastapi import APIRouter

from ....schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> HealthResponse:
    return HealthResponse(status="healthy")
