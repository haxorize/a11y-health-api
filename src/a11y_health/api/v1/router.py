from fastapi import APIRouter

from a11y_health.api.v1.endpoints import (
    apps,
    brands,
    findings,
    health,
    org_units,
    scan_runs,
    scores,
    scoring_vocabulary,
)
from a11y_health.config import settings

api_router = APIRouter(prefix=settings.API_V1_PREFIX)
api_router.include_router(health.router)
api_router.include_router(org_units.router)
api_router.include_router(brands.router)
api_router.include_router(apps.router)
api_router.include_router(scan_runs.app_router)
api_router.include_router(scan_runs.router)
api_router.include_router(scan_runs.pages_router)
api_router.include_router(findings.router)
api_router.include_router(scores.router)
api_router.include_router(scoring_vocabulary.router)
