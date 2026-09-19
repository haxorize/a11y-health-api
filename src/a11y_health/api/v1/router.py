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
from a11y_health.config import Settings


def create_api_router(settings: Settings) -> APIRouter:
    """Every v1 route under the prefix the settings handed in declare.

    A factory for the same reason `create_app` is one: the prefix reaches the
    path of every operation in `openapi.json`, so a module-level router built
    from the process's settings puts a developer's `API_V1_PREFIX` into the
    exported spec. The endpoint routers below carry no setting and stay
    module-level.
    """
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
    return api_router
