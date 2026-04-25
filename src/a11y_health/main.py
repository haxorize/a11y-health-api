from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import ValidationError
from sqlalchemy import text
from starlette.requests import Request

from a11y_health.api.v1.router import api_router
from a11y_health.config import settings
from a11y_health.core.database import engine
from a11y_health.core.exceptions import (
    CircularReferenceError,
    DuplicateSlugError,
    HasDependentsError,
    InvalidStatusTransitionError,
    NotFoundError,
    ScanRunCompletedError,
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    yield
    await engine.dispose()


def _operation_id(route: APIRoute) -> str:
    # Drives generated SDK method names; keep stable.
    return route.name


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


_EXCEPTION_STATUS_CODES: dict[type[Exception], int] = {
    NotFoundError: 404,
    CircularReferenceError: 409,
    DuplicateSlugError: 409,
    HasDependentsError: 409,
    InvalidStatusTransitionError: 409,
    ScanRunCompletedError: 409,
}


def _make_handler(status: int) -> Callable[..., Coroutine[Any, Any, JSONResponse]]:
    async def handler(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    return handler


for _exc_cls, _status_code in _EXCEPTION_STATUS_CODES.items():
    app.exception_handler(_exc_cls)(_make_handler(_status_code))


@app.exception_handler(ValidationError)
async def _validation_error_handler(_request: Request, exc: ValidationError) -> JSONResponse:
    err = exc.errors()[0]
    loc = " → ".join(str(part) for part in err["loc"])
    return JSONResponse(status_code=422, content={"detail": f"{loc}: {err['msg']}"})


app.include_router(api_router)
