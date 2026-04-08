from fastapi import APIRouter

from a11y_health.api.v1.endpoints import health
from a11y_health.config import settings

api_router = APIRouter(prefix=settings.API_V1_PREFIX)
api_router.include_router(health.router)
