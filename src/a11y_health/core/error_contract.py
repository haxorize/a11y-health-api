"""The Error Contract: the single table mapping each domain error mode to its
HTTP status and Error Code.

Handler registration, response bodies, and per-operation OpenAPI declarations
all derive from `ERROR_MODES`, so runtime behavior and the contract cannot
drift apart. Route authors declare escaping modes via `error_responses()` in
domain vocabulary and never touch a status code.

See `docs/architecture.md` ("How errors become HTTP status codes").
"""

from typing import Any, Final, NamedTuple

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

# Re-exported: `ErrorCode` and `ErrorBody` are declared next to their lenient
# twin in `error_body`, which carries no web-framework import. Every route
# still reaches them through this module, which owns what they mean.
from a11y_health.core.error_body import ErrorBody, ErrorCode
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

# The vendor extension under which a declaration carries its own code set, and
# the published key downstream clients read off the OpenAPI document. Public
# because every reader sits outside src: the suite's declaration guards read
# back what `error_responses()` wrote here. The lockstep that earns the name is
# with Declaration Honesty, which used to come from the two sides sharing a
# file; this name is what carries it now that they don't (ADR 0033).
ERROR_CODES_KEY: Final = "x-error-codes"


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
    """Build a route's `responses=` declaration from the modes that escape it.

    Codes sharing a status collapse into one declaration; `ERROR_CODES_KEY`
    carries the per-operation code set machine-readably.
    """
    by_status: dict[int, list[ErrorCode]] = {}
    for code in codes:
        by_status.setdefault(_STATUS_BY_CODE[code], []).append(code)
    return {
        status: {
            "model": ErrorBody,
            "description": f"Domain error: {' | '.join(sorted(group))}",
            ERROR_CODES_KEY: sorted(group),
        }
        for status, group in sorted(by_status.items())
    }
