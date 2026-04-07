from fastapi import APIRouter

from a11y_quality.api.v1.endpoints import health
from a11y_quality.config import settings

api_router = APIRouter(prefix=settings.API_V1_PREFIX)
api_router.include_router(health.router)
