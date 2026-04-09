from fastapi import APIRouter

from a11y_health.api.v1.endpoints import apps, health, org_units, scan_runs
from a11y_health.config import settings

api_router = APIRouter(prefix=settings.API_V1_PREFIX)
api_router.include_router(health.router)
api_router.include_router(org_units.router)
api_router.include_router(apps.router)
api_router.include_router(scan_runs.app_router)
api_router.include_router(scan_runs.router)
