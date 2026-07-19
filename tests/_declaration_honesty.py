"""ASGI plumbing for suite-wide declaration honesty; the contract knowledge
lives in `error_contract`. The shim checks every observed error response; the
rollup instrumentation checks the one mode responses never show organically
(rollup-race 409s) at its raise site instead.

See `docs/architecture.md` ("How errors become HTTP status codes").
"""

import functools
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from a11y_health.core.error_contract import (
    FRAMEWORK_STATUSES,
    ErrorCode,
    assert_declared_mode,
    assert_raisable_mode_declared,
    operation_key,
    operations_declaring,
)
from a11y_health.services import score_snapshot

_current_request_scope: ContextVar[Any] = ContextVar("_current_request_scope", default=None)

OBSERVED_ROLLUP_OPERATIONS: set[tuple[str, str]] = set()


def stale_rollup_declaration_message(app: Any) -> str | None:
    """The reverse direction of ADR 0033 (#121): the failure text naming every
    operation that declares the retryable concurrent_rollup mode without any
    test having observed it reach a rollup, or None when none is stale. Only
    meaningful after a full suite run — conftest's sessionfinish hook owns that
    gating.
    """
    stale = operations_declaring(app, ErrorCode.CONCURRENT_ROLLUP) - OBSERVED_ROLLUP_OPERATIONS
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
    # The raisers are every public rollup_* callable — the module's naming
    # convention for the surface through which ConcurrentRollupError can escape
    # (today the #98 same-observation guard and the #104 deadlock translation,
    # both reachable only via rollup_org_unit_scores / rollup_brand_scores).
    # A raiser named outside the convention would escape (ADR 0033 residual);
    # a non-raising rollup_* function would over-assert, which fails loudly.
    for name in dir(score_snapshot):
        raiser = getattr(score_snapshot, name)
        if not name.startswith("rollup_") or not callable(raiser):
            continue
        if hasattr(raiser, "__wrapped__"):  # already instrumented
            continue
        setattr(score_snapshot, name, _enforcing(raiser))


def _enforcing(raiser: Any) -> Any:
    @functools.wraps(raiser)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        scope = _current_request_scope.get()
        route = scope.get("route") if scope is not None else None
        if route is not None:
            assert_raisable_mode_declared(scope["method"], route, ErrorCode.CONCURRENT_ROLLUP, app=scope.get("app"))
            OBSERVED_ROLLUP_OPERATIONS.add(operation_key(scope["method"], route))
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
                if 400 <= status < 500 and status not in FRAMEWORK_STATUSES and route is not None:
                    pending_status = status
            elif message["type"] == "http.response.body" and pending_status is not None:
                body += message.get("body", b"")
                if not message.get("more_body", False):
                    assert_declared_mode(
                        scope["method"], scope["path"], route, pending_status, body, app=scope.get("app")
                    )
                    pending_status = None
                    body = b""
            await send(message)

        with request_scope(scope):
            await self.inner(scope, receive, send_wrapper)
