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


# The startup probe: an unreachable database fails the boot rather than the
# first request. It is single-shot on purpose: retrying is left to whatever
# restarts the process.
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    yield
    await engine.dispose()


def _operation_id(route: APIRoute) -> str:
    # The operation id is the route function name, and that name becomes the
    # UI's generated method name, so renaming a route function renames the
    # method: keep the names stable. Keep them unique repo-wide too: two
    # endpoint functions sharing one across routers write a duplicate id into
    # openapi.json and break UI codegen (docs/architecture.md, "The OpenAPI
    # contract pipeline").
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
