from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute
from sqlalchemy import text

from a11y_health.api.v1.router import create_api_router
from a11y_health.config import Settings, settings
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


def create_app(settings: Settings) -> FastAPI:
    """The application as the settings handed in declare it.

    A factory rather than module-scope construction, so a caller needing an app
    under settings other than the process's own builds one instead of rebinding
    the singleton and relying on import order to make that stick.
    `scripts/export_openapi.py` is the only such caller, and its whole reason is
    that the spec must not vary by machine.

    The v1 router is built here rather than imported, because `API_V1_PREFIX`
    reaches the path of every operation in the spec — an imported module-level
    router would put the exporting machine's prefix into the artifact, which is
    the exact leak this factory exists to close.

    The database engine is deliberately *not* a parameter: it stays
    `core.database`'s module-level one, built from the settings in force at
    import. The caller above never opens a connection, since `lifespan` runs
    only under a server, and nothing else needs two engines yet.
    """
    app = FastAPI(
        title=settings.PROJECT_NAME,
        version=settings.VERSION,
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
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
    app.include_router(create_api_router(settings))
    return app


# What `uvicorn a11y_health.main:app` and the suite import.
app = create_app(settings)
