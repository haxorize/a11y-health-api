from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from sqlalchemy import text

from a11y_health.api.v1.router import api_router
from a11y_health.config import API_V1_PREFIX, PROJECT_NAME, VERSION, settings
from a11y_health.core.database import engine
from a11y_health.core.error_contract import register_error_handlers


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    yield
    await engine.dispose()


def _operation_id(route: APIRoute) -> str:
    # Drives generated SDK method names; keep stable. Operation ID is the route
    # function name, so two endpoint functions sharing a name across routers
    # will collide in openapi.json and break UI codegen — keep route function
    # names unique repo-wide.
    return route.name


app = FastAPI(
    title=PROJECT_NAME,
    version=VERSION,
    openapi_url=f"{API_V1_PREFIX}/openapi.json",
    lifespan=lifespan,
    generate_unique_id_function=_operation_id,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
register_error_handlers(app)
app.include_router(api_router)
