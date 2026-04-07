from fastapi import APIRouter

from ...config import settings
from .endpoints import health

api_router = APIRouter(prefix=settings.API_V1_PREFIX)
api_router.include_router(health.router)
