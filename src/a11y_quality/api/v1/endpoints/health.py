from fastapi import APIRouter

from a11y_quality.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check() -> HealthResponse:
    return HealthResponse(status="healthy")
