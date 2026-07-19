"""The Error Contract: the single table mapping each domain error mode to its
HTTP status and Error Code.

Handler registration, response bodies, and per-operation OpenAPI declarations
all derive from `ERROR_MODES`, so runtime behavior and the contract cannot
drift apart. Route authors declare escaping modes via `error_responses()` in
domain vocabulary and never touch a status code.

See `docs/architecture.md` ("How errors become HTTP status codes").
"""

import enum
from typing import Any, NamedTuple

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.routing import iter_route_contexts
from pydantic import BaseModel, ValidationError
from starlette.requests import Request

from a11y_health.core.exceptions import (
    CircularReferenceError,
    ConcurrentRollupError,
    DomainError,
    DuplicateRootError,
    DuplicateSlugError,
    EmptyScanRunError,
    HasDependentsError,
    InvalidAxePayloadError,
    InvalidStatusTransitionError,
    NotFoundError,
    ScanRunCompletedError,
)
from a11y_health.core.pagination import InvalidCursorError


class ErrorCode(enum.StrEnum):
    NOT_FOUND = enum.auto()
    DUPLICATE_ROOT = enum.auto()
    DUPLICATE_SLUG = enum.auto()
    HAS_DEPENDENTS = enum.auto()
    INVALID_STATUS_TRANSITION = enum.auto()
    SCAN_RUN_COMPLETED = enum.auto()
    EMPTY_SCAN_RUN = enum.auto()
    CIRCULAR_REFERENCE = enum.auto()
    CONCURRENT_ROLLUP = enum.auto()
    INVALID_CURSOR = enum.auto()
    INVALID_AXE_PAYLOAD = enum.auto()


class ErrorBody(BaseModel):
    code: ErrorCode
    message: str


class _Mode(NamedTuple):
    status: int
    code: ErrorCode


ERROR_MODES: dict[type[DomainError], _Mode] = {
    NotFoundError: _Mode(404, ErrorCode.NOT_FOUND),
    DuplicateRootError: _Mode(409, ErrorCode.DUPLICATE_ROOT),
    DuplicateSlugError: _Mode(409, ErrorCode.DUPLICATE_SLUG),
    HasDependentsError: _Mode(409, ErrorCode.HAS_DEPENDENTS),
    InvalidStatusTransitionError: _Mode(409, ErrorCode.INVALID_STATUS_TRANSITION),
    ScanRunCompletedError: _Mode(409, ErrorCode.SCAN_RUN_COMPLETED),
    EmptyScanRunError: _Mode(409, ErrorCode.EMPTY_SCAN_RUN),
    CircularReferenceError: _Mode(409, ErrorCode.CIRCULAR_REFERENCE),
    ConcurrentRollupError: _Mode(409, ErrorCode.CONCURRENT_ROLLUP),
    InvalidCursorError: _Mode(400, ErrorCode.INVALID_CURSOR),
    InvalidAxePayloadError: _Mode(400, ErrorCode.INVALID_AXE_PAYLOAD),
}

_STATUS_BY_CODE: dict[ErrorCode, int] = {mode.code: mode.status for mode in ERROR_MODES.values()}


def response_for(exc: DomainError) -> JSONResponse:
    """Render a domain error as its table-declared status and coded body.

    Lookup is exact by exception type — the exhaustiveness test guarantees
    every mode its own row. Raises `LookupError` for a `DomainError` with no
    table entry — that is a contract gap, and it must surface as a 500, not a
    disguised client error.
    """
    mode = ERROR_MODES.get(type(exc))
    if mode is None:
        raise LookupError(f"{type(exc).__name__} has no ERROR_MODES entry")
    body = ErrorBody(code=mode.code, message=str(exc))
    return JSONResponse(status_code=mode.status, content=body.model_dump(mode="json"))


async def _handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    return response_for(exc)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _handler)


def error_responses(*codes: ErrorCode) -> dict[int | str, dict[str, Any]]:
    """Build a route's `responses=` declaration from the modes that can escape it.

    Codes sharing a status collapse into one declaration; `x-error-codes`
    carries the per-operation code set machine-readably (the honesty shim in
    tests checks observed bodies against it).
    """
    by_status: dict[int, list[ErrorCode]] = {}
    for code in codes:
        by_status.setdefault(_STATUS_BY_CODE[code], []).append(code)
    return {
        status: {
            "model": ErrorBody,
            "description": f"Domain error: {' | '.join(sorted(group))}",
            "x-error-codes": sorted(group),
        }
        for status, group in sorted(by_status.items())
    }


# 4xx statuses FastAPI/Starlette produce themselves (405 method-not-allowed,
# 422 request-shape validation) — never coded, never declared per operation.
FRAMEWORK_STATUSES: frozenset[int] = frozenset({405, 422})


def _effective_route(app: FastAPI | None, route: Any) -> Any:
    """Resolve a matched route to the declaration view the OpenAPI document is
    generated from. FastAPI's non-copying include keeps
    `include_router(responses=...)` declarations off `route.responses`; the
    merged view lives on the route's include context, read here through the
    same iterator OpenAPI generation uses. Falls back to the route itself when
    there is no app or no context (e.g. synthetic test scopes) — a view that
    can only under-report declarations, so honesty fails loud, never passes
    falsely.
    """
    if app is None:
        return route
    for context in iter_route_contexts(app.routes):
        if context.original_route is route:
            return context
    return route


def assert_raisable_mode_declared(method: str, route: Any, code: ErrorCode, app: FastAPI | None = None) -> None:
    """Declaration honesty asserted at the raise site instead of the response,
    for modes no test observes organically — applied suite-wide by the
    instrumentation in `tests/_declaration_honesty.py`. Checked against the
    operation's effective declaration (include-level responses merged in) when
    `app` is given. The failure message names the operation by its route
    template, not the concrete request path.
    """
    route = _effective_route(app, route)
    declared_codes = getattr(route, "responses", {}).get(_STATUS_BY_CODE[code], {}).get("x-error-codes", [])
    assert code in declared_codes, (
        f"{method} {route.path} can produce error code {code} but does not declare it — "
        f"add ErrorCode.{code.name} to the operation's error_responses()"
    )


def assert_declared_mode(
    method: str, path: str, route: Any, status: int, body: bytes, app: FastAPI | None = None
) -> None:
    """Declaration honesty, applied suite-wide by the test shim in
    `tests/_declaration_honesty.py`. Raises `AssertionError` on an observed
    4xx whose mode is not declared on the operation — checked against the
    operation's effective declaration (include-level responses merged in) when
    `app` is given.
    """
    declared = getattr(_effective_route(app, route), "responses", {})
    assert status in declared, (
        f"{method} {path} returned {status}, which is not declared on the "
        f"operation — declare the mode via error_responses()"
    )
    declared_codes = declared[status].get("x-error-codes")
    assert declared_codes is not None, (
        f"{method} {path} declares {status} without x-error-codes — "
        f"declare it via error_responses(), not a hand-written responses entry"
    )
    try:
        parsed = ErrorBody.model_validate_json(body)
    except ValidationError:
        raise AssertionError(
            f"{method} {path} returned declared {status} with a body that is not a coded ErrorBody: {body[:200]!r}"
        ) from None
    assert parsed.code in declared_codes, (
        f"{method} {path} produced error code {parsed.code!r}, which is not "
        f"among the operation's declared modes {declared_codes}"
    )
