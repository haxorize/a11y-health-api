"""The ADR 0033 Declaration Honesty mechanism, whole: the audit that reads what
an operation declared, the ASGI shim that checks every observed error response
against it, and the instrumentation that catches the one mode responses never
show organically (rollup-race 409s) at its raise site — the Owner Dispatcher's
rollup entrypoint — and the session gate that diffs what that instrumentation
observed against what is declared once a full run finishes.

The charter is closed: this mechanism, nothing else. The audit lives here rather
than in `error_contract` because no production code consumes it; what crosses
the seam instead is the contract's own vocabulary plus `ERROR_CODES_KEY`, which
ties what `error_responses()` writes to what `_declared_codes` reads. Should
production ever need declaration introspection, the function it needs is
*promoted* back into `error_contract` — never copied.

See `docs/architecture.md` ("How errors become HTTP status codes").
"""

import functools
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Protocol

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts
from pydantic import ValidationError

from a11y_health.core.error_contract import (
    ERROR_CODES_KEY,
    ErrorBody,
    ErrorCode,
)
from a11y_health.main import app
from a11y_health.services import owner

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
    can only under-report declarations, so Declaration Honesty fails loud. A
    router mounted more than once shares one route object across contexts and
    the first match wins, which could over-report for a less-declaring mount —
    an ADR 0033 residual; no router is mounted twice today.
    """
    if app is None:
        return route
    for context in iter_route_contexts(app.routes):
        if context.original_route is route:
            return context
    return route


def _declared_codes(view: Any) -> set[ErrorCode]:
    # Read across statuses rather than indexing one. `error_responses()` buckets
    # each code under exactly one status, so the union answers "is this code
    # declared here?" identically — without the audit having to derive a second
    # code-to-status map from the contract's table and keep it in lockstep.
    responses = getattr(view, "responses", {})
    return {code for entry in responses.values() for code in entry.get(ERROR_CODES_KEY, [])}


def _operation_key(method: str, route: Any) -> tuple[str, str]:
    # The identity both sides of the reverse-direction rollup diff key on (ADR
    # 0033, #121): the route's own template, include prefix excluded.
    return (method, route.path)


def _operations_declaring(app: FastAPI, code: ErrorCode) -> set[tuple[str, str]]:
    """The operations whose effective declaration (include-level responses
    merged in) carries `code` — the declared side of the reverse-direction
    rollup diff.
    """
    operations: set[tuple[str, str]] = set()
    for context in iter_route_contexts(app.routes):
        route = context.original_route
        if isinstance(route, APIRoute) and code in _declared_codes(context):
            operations.update(_operation_key(method, route) for method in route.methods or ())
    return operations


def _assert_raisable_mode_declared(method: str, route: Any, code: ErrorCode, app: FastAPI | None) -> None:
    """Declaration Honesty asserted at the raise site instead of the response,
    for modes no test observes organically. The failure message names the
    operation by its route template, not the concrete request path.
    """
    route = _effective_route(app, route)
    assert code in _declared_codes(route), (
        f"{method} {route.path} can produce error code {code} but does not declare it — "
        f"add ErrorCode.{code.name} to the operation's error_responses()"
    )


def _assert_declared_mode(method: str, path: str, route: Any, status: int, body: bytes, app: FastAPI | None) -> None:
    declared = getattr(_effective_route(app, route), "responses", {})
    assert status in declared, (
        f"{method} {path} returned {status}, which is not declared on the "
        f"operation — declare the mode via error_responses()"
    )
    # Read by observed status rather than through `_declared_codes`, which
    # unions across statuses and cannot say which one carried the code — and
    # which defaults a missing key to [], where the next assert has to tell
    # "declared without codes" apart from "declared with none". This is the one
    # reader that still checks a code against the status it actually came back
    # on; `_declared_codes` deliberately does not.
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

_OBSERVED_ROLLUP_OPERATIONS: set[tuple[str, str]] = set()


def record_observation(key: tuple[str, str]) -> None:
    _OBSERVED_ROLLUP_OPERATIONS.add(key)


@dataclass
class Observation:
    observed: bool = False


@contextmanager
def observation_scope(key: tuple[str, str], *, synthetic: bool = False) -> Iterator[Observation]:
    """Clear `key` for the block, so what the yielded `Observation` reports
    once the block exits is the block's own doing, then restore it. An
    observation made in the block survives only when it is real: a synthetic
    one would mask a same-keyed stale declaration at session finish.
    """
    earlier = key in _OBSERVED_ROLLUP_OPERATIONS
    _OBSERVED_ROLLUP_OPERATIONS.discard(key)
    observation = Observation()
    try:
        yield observation
    finally:
        observation.observed = key in _OBSERVED_ROLLUP_OPERATIONS
        _OBSERVED_ROLLUP_OPERATIONS.discard(key)
        if earlier or (observation.observed and not synthetic):
            _OBSERVED_ROLLUP_OPERATIONS.add(key)


def stale_rollup_declaration_message(app: Any) -> str | None:
    """The reverse direction of ADR 0033 (#121): the failure text naming every
    operation that declares the retryable concurrent_rollup mode without any
    test having observed it reach a rollup, or None when none is stale. Only
    meaningful after a full suite run — `pytest_sessionfinish` below owns that
    gating.
    """
    stale = _operations_declaring(app, ErrorCode.CONCURRENT_ROLLUP) - _OBSERVED_ROLLUP_OPERATIONS
    if not stale:
        return None
    operations = ", ".join(f"{method} {path}" for method, path in sorted(stale))
    return (
        f"stale concurrent_rollup declaration(s): {operations} — no test observed these "
        "operations reaching a rollup; drop ErrorCode.CONCURRENT_ROLLUP from their "
        "error_responses() or restore the rollup trigger"
    )


@contextmanager
def _request_scope(scope: Any) -> Iterator[None]:
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
            record_observation(_operation_key(scope["method"], route))
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

        with _request_scope(scope):
            await self.inner(scope, receive, send_wrapper)


# The session gate for the reverse direction: the diff runs only after a green
# full run, and the narrowings it skips and its residuals are ADR 0033's
# "Reverse direction" entry. The hooks below track deselection and execution
# themselves rather than reading another plugin's bookkeeping.
_deselected = False
_tests_ran = 0


class _Options(Protocol):
    def getoption(self, name: str) -> Any: ...


def run_was_narrowed(config: _Options, *, deselected: bool, tests_ran: int) -> bool:
    return (
        deselected
        or not tests_ran
        or any(config.getoption(option) for option in ("file_or_dir", "ignore", "ignore_glob"))
    )


def pytest_deselected(items: Sequence[pytest.Item]) -> None:
    global _deselected
    if items:
        _deselected = True


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    global _tests_ran
    if report.when == "call":
        _tests_ran += 1


# Failure sets session.exitstatus instead of raising pytest.exit: wrap_session
# returns the mutated value, and an exception here would abort the terminal
# reporter's sessionfinish wrapper before it prints the run summary.
@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    config = session.config
    reporter = config.pluginmanager.get_plugin("terminalreporter")
    if exitstatus != 0 or reporter is None:
        return
    if run_was_narrowed(config, deselected=_deselected, tests_ran=_tests_ran):
        return
    message = stale_rollup_declaration_message(app)
    if message is not None:
        reporter.write_sep("!", message, red=True)
        session.exitstatus = 1
