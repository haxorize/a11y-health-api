from fastapi import APIRouter

from a11y_health.api.v1.endpoints import health, org_units
from a11y_health.config import settings

api_router = APIRouter(prefix=settings.API_V1_PREFIX)
api_router.include_router(health.router)
api_router.include_router(org_units.router)
