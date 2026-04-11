from collections.abc import AsyncIterator, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from starlette.requests import Request

from a11y_health.api.v1.router import api_router
from a11y_health.config import settings
from a11y_health.core.database import engine
from a11y_health.core.exceptions import (
    CircularReferenceError,
    DuplicateSlugError,
    HasDependentsError,
    InvalidAxePayloadError,
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


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
    lifespan=lifespan,
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
    InvalidAxePayloadError: 422,
}

for _exc_cls, _status_code in _EXCEPTION_STATUS_CODES.items():

    def _make_handler(status: int) -> Callable[..., Coroutine[Any, Any, JSONResponse]]:
        async def handler(_request: Request, exc: Exception) -> JSONResponse:
            return JSONResponse(status_code=status, content={"detail": str(exc)})

        return handler

    app.exception_handler(_exc_cls)(_make_handler(_status_code))


app.include_router(api_router)
