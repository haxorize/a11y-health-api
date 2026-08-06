"""The ADR 0033 Declaration Honesty mechanism, whole: the audit that reads what
an operation declared, the ASGI shim that checks every observed error response
against it, and the instrumentation that catches the one mode responses never
show organically (rollup-race 409s) at its raise site — the Owner Dispatcher's
rollup entrypoint.

The charter is closed: this mechanism, nothing else. The audit lives here rather
than in `error_contract` because no production code consumes it; what crosses
the seam instead is the contract's own vocabulary plus `ERROR_CODES_KEY`, which
ties what `error_responses()` writes to what `_declared_codes` reads. Should
production ever need declaration introspection, the function it needs is
*promoted* back into `error_contract` — never copied.

See `docs/architecture.md` ("How errors become HTTP status codes").
"""

import functools
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts
from pydantic import ValidationError

from a11y_health.core.error_contract import (
    ERROR_CODES_KEY,
    ERROR_MODES,
    ErrorBody,
    ErrorCode,
)
from a11y_health.services import owner

# Derived from the contract's public table rather than reaching for its private
# twin, which would be a second name crossing the seam. Both sides read the one
# table, and the round-trip tests — declarations built through error_responses()
# and read back through the audit — are what catch a derivation that drifts.
_STATUS_BY_CODE: dict[ErrorCode, int] = {mode.code: mode.status for mode in ERROR_MODES.values()}

# 4xx statuses FastAPI/Starlette produce themselves (405 method-not-allowed,
# 422 request-shape validation) — never coded, never declared per operation.
_FRAMEWORK_STATUSES: frozenset[int] = frozenset({405, 422})


def _effective_route(app: FastAPI | None, route: Any) -> Any:
    """Resolve a matched route to the declaration view the OpenAPI document is
    generated from. FastAPI's non-copying include keeps
    `include_router(responses=...)` declarations off `route.responses`; the
    merged view lives on the route's include context, read here through the
    same iterator OpenAPI generation uses. Falls back to the route itself when
    there is no app or no context (e.g. synthetic test scopes) — a view that
    can only under-report declarations, so honesty fails loud. A router mounted
    more than once shares one route object across contexts and the first match
    wins, which could over-report for a less-declaring mount — an ADR 0033
    residual; no router is mounted twice today.
    """
    if app is None:
        return route
    for context in iter_route_contexts(app.routes):
        if context.original_route is route:
            return context
    return route


def _declared_codes(view: Any, status: int) -> list[ErrorCode]:
    return getattr(view, "responses", {}).get(status, {}).get(ERROR_CODES_KEY, [])


def _operation_key(method: str, route: Any) -> tuple[str, str]:
    # The identity both sides of the reverse-direction rollup diff key on (ADR
    # 0033, #121): the route's own template, include prefix excluded.
    return (method, route.path)


def _operations_declaring(app: FastAPI, code: ErrorCode) -> set[tuple[str, str]]:
    """The operations whose effective declaration (include-level responses
    merged in) carries `code` — the declared side of the reverse-direction
    rollup diff.
    """
    status = _STATUS_BY_CODE[code]
    operations: set[tuple[str, str]] = set()
    for context in iter_route_contexts(app.routes):
        route = context.original_route
        if isinstance(route, APIRoute) and code in _declared_codes(context, status):
            operations.update(_operation_key(method, route) for method in route.methods or ())
    return operations


def _assert_raisable_mode_declared(method: str, route: Any, code: ErrorCode, app: FastAPI | None) -> None:
    """Declaration honesty asserted at the raise site instead of the response,
    for modes no test observes organically. The failure message names the
    operation by its route template, not the concrete request path.
    """
    route = _effective_route(app, route)
    declared_codes = _declared_codes(route, _STATUS_BY_CODE[code])
    assert code in declared_codes, (
        f"{method} {route.path} can produce error code {code} but does not declare it — "
        f"add ErrorCode.{code.name} to the operation's error_responses()"
    )


def _assert_declared_mode(method: str, path: str, route: Any, status: int, body: bytes, app: FastAPI | None) -> None:
    declared = getattr(_effective_route(app, route), "responses", {})
    assert status in declared, (
        f"{method} {path} returned {status}, which is not declared on the "
        f"operation — declare the mode via error_responses()"
    )
    # Read directly rather than through `_declared_codes`, which defaults a
    # missing key to []: the next assert has to tell "declared without codes"
    # apart from "declared with none".
    declared_codes = declared[status].get(ERROR_CODES_KEY)
    assert declared_codes is not None, (
        f"{method} {path} declares {status} without {ERROR_CODES_KEY} — "
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


_current_request_scope: ContextVar[Any] = ContextVar("_current_request_scope", default=None)

OBSERVED_ROLLUP_OPERATIONS: set[tuple[str, str]] = set()


def stale_rollup_declaration_message(app: Any) -> str | None:
    """The reverse direction of ADR 0033 (#121): the failure text naming every
    operation that declares the retryable concurrent_rollup mode without any
    test having observed it reach a rollup, or None when none is stale. Only
    meaningful after a full suite run — conftest's sessionfinish hook owns that
    gating.
    """
    stale = _operations_declaring(app, ErrorCode.CONCURRENT_ROLLUP) - OBSERVED_ROLLUP_OPERATIONS
    if not stale:
        return None
    operations = ", ".join(f"{method} {path}" for method, path in sorted(stale))
    return (
        f"stale concurrent_rollup declaration(s): {operations} — no test observed these "
        "operations reaching a rollup; drop ErrorCode.CONCURRENT_ROLLUP from their "
        "error_responses() or restore the rollup trigger"
    )


@contextmanager
def request_scope(scope: Any) -> Iterator[None]:
    token = _current_request_scope.set(scope)
    try:
        yield
    finally:
        _current_request_scope.reset(token)


def instrument_rollup_raisers() -> None:
    # The raisers are every public rollup* callable on the Owner Dispatcher —
    # the naming convention for the surface through which ConcurrentRollupError
    # can escape (today the #98 same-observation guard and the #104 deadlock
    # translation, both reachable only via owner.rollup). A raiser named
    # outside the convention would escape (ADR 0033 residual); a non-raising
    # rollup* function would over-assert, which fails loudly.
    for name in dir(owner):
        raiser = getattr(owner, name)
        if not name.startswith("rollup") or not callable(raiser):
            continue
        if hasattr(raiser, "__wrapped__"):  # already instrumented
            continue
        setattr(owner, name, _enforcing(raiser))


def _enforcing(raiser: Any) -> Any:
    @functools.wraps(raiser)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        scope = _current_request_scope.get()
        route = scope.get("route") if scope is not None else None
        if route is not None:
            _assert_raisable_mode_declared(scope["method"], route, ErrorCode.CONCURRENT_ROLLUP, app=scope.get("app"))
            OBSERVED_ROLLUP_OPERATIONS.add(_operation_key(scope["method"], route))
        return await raiser(*args, **kwargs)

    return wrapper


class DeclarationHonestyShim:
    def __init__(self, inner: Any) -> None:
        self.inner = inner

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        pending_status: int | None = None
        body = b""

        async def send_wrapper(message: Any) -> None:
            nonlocal pending_status, body
            route = scope.get("route")
            if message["type"] == "http.response.start":
                status = message["status"]
                if 400 <= status < 500 and status not in _FRAMEWORK_STATUSES and route is not None:
                    pending_status = status
            elif message["type"] == "http.response.body" and pending_status is not None:
                body += message.get("body", b"")
                if not message.get("more_body", False):
                    _assert_declared_mode(
                        scope["method"], scope["path"], route, pending_status, body, app=scope.get("app")
                    )
                    pending_status = None
                    body = b""
            await send(message)

        with request_scope(scope):
            await self.inner(scope, receive, send_wrapper)
