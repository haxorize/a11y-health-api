import asyncio
import socket
from collections.abc import AsyncIterator
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest
import uvicorn
from sqlalchemy.ext.asyncio import AsyncEngine

from a11y_health.cli._client import make_client
from a11y_health.core.database import SessionSource, bind_session_source, session_source
from tests.conftest import declaration_honest_app


@pytest.fixture
async def no_server() -> AsyncIterator[httpx.AsyncClient]:
    """A client that fails the test if anything reaches the transport.

    For the operations that fail while reading the directory, before the first
    request. Passing this instead of `db_client` asserts the failure is local —
    a regression that moved the check after the lookup fails here, where a real
    client would quietly pass.
    """

    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError(f"expected no request, got {request.method} {request.url}")

    async with httpx.AsyncClient(transport=httpx.MockTransport(refuse), base_url="http://no-server") as client:
        yield client


# A request carrying this header never reaches the app; the fake proxy in
# front of it answers instead, the way a real one misbehaves on whatever path
# it is handed. `stall` holds the response until the client gives up, so the
# stall lasts exactly as long as the client's patience and never delays
# shutdown; `redirect` bounces to a real route; `body-limit` answers a POST
# declaring more than PROXY_BODY_LIMIT bytes with an HTML 413 before reading
# the body and closes the connection, as an ingress with a request-size cap
# does (#140) — smaller requests still reach the app.
PROXY_HEADER = "x-test-proxy"
PROXY_STALL = "stall"
PROXY_REDIRECT = "redirect"
PROXY_BODY_LIMIT = "body-limit"
PROXY_BODY_LIMIT_BYTES = 4096


@dataclass
class Forwarded:
    """One request the proxy handed to the app, as the wire saw it: the TCP
    peer it arrived on, the headers the client put on the socket, and the
    headers the app's response left with. A reuse assertion over `peer` rests
    on an assumption, not a guarantee: the kernel hands each new connection a
    fresh ephemeral port and holds a closed one in TIME_WAIT, so within one
    test a repeated peer is the same connection."""

    peer: tuple[str, int]
    method: str
    path: str
    request_headers: httpx.Headers
    response_headers: httpx.Headers = field(default_factory=httpx.Headers)


class _FakeProxy:
    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.forwarded: list[Forwarded] = []

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.inner(scope, receive, send)
            return
        request_headers = httpx.Headers(scope["headers"])
        behavior = request_headers.get(PROXY_HEADER)
        if behavior == PROXY_STALL:
            while (await receive())["type"] != "http.disconnect":
                pass
        elif behavior == PROXY_REDIRECT:
            await send({"type": "http.response.start", "status": 307, "headers": [(b"location", b"/api/v1/brands")]})
            await send({"type": "http.response.body", "body": b""})
        elif behavior == PROXY_BODY_LIMIT and int(request_headers.get("content-length", 0)) > PROXY_BODY_LIMIT_BYTES:
            headers = [(b"content-type", b"text/html"), (b"connection", b"close")]
            await send({"type": "http.response.start", "status": 413, "headers": headers})
            await send({"type": "http.response.body", "body": b"<html><body>Request Entity Too Large</body></html>"})
        else:
            record = Forwarded(tuple(scope["client"]), scope["method"], scope["path"], request_headers)
            self.forwarded.append(record)

            async def send_recording(message: Any) -> None:
                if message["type"] == "http.response.start":
                    record.response_headers = httpx.Headers(message["headers"])
                await send(message)

            await self.inner(scope, receive, send_recording)


@pytest.fixture(scope="session")
def _fake_proxy() -> _FakeProxy:
    return _FakeProxy(declaration_honest_app)


@pytest.fixture(scope="session")
async def live_server(_fake_proxy: _FakeProxy, engine: AsyncEngine) -> AsyncIterator[str]:
    """The real app on a real port, as the base URL a client with no transport
    override reaches it at, with its requests on real-commit sessions from
    the test engine.

    uvicorn runs as a task on the suite's session loop rather than in a thread
    or a subprocess, so the served app shares the Declaration Honesty request
    scope (ADR 0033). The session source is bound to the test engine for the
    server's lifetime, and read back so a missing binding fails at setup
    rather than writing rows, because a server's requests cannot join a
    test's rolled-back transaction and unbound they would reach the dev
    `DATABASE_URL`; a test that writes through the server takes
    `committed_session_factory` for the truncate at teardown (ADR 0011). Over
    a socket an undeclared mode does not surface as the shim's assertion
    text: the status line is on the wire before the shim asserts on the body,
    so the client sees a torn connection instead. Lifespan is off, because
    its shutdown disposes the bound engine, which is the suite's own;
    `tests/test_main.py` runs it against an engine of its own.
    """
    config = uvicorn.Config(_fake_proxy, lifespan="off", log_level="warning")
    server = uvicorn.Server(config)
    # Bound here rather than by uvicorn, so the port is read off a socket the
    # fixture owns instead of out of the server's internals.
    with socket.socket() as sock, bind_session_source(SessionSource(engine)):
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        assert session_source().engine is engine
        serving = asyncio.create_task(server.serve(sockets=[sock]))
        try:
            async with asyncio.timeout(5):
                while not server.started:
                    if serving.done():
                        serving.result()
                    await asyncio.sleep(0.01)
            yield f"http://127.0.0.1:{port}"
        finally:
            server.should_exit = True
            if not server.started:
                serving.cancel()
            with suppress(asyncio.CancelledError):
                await serving


@pytest.fixture
async def socket_client(live_server: str, _fake_proxy: _FakeProxy) -> AsyncIterator[httpx.AsyncClient]:
    """The client `a11y` ships (`make_client`: its transport, timeout, and
    headers) against `live_server`. The proxy's record window opens here,
    since the server outlives the test."""
    _fake_proxy.forwarded.clear()
    async with make_client(live_server) as client:
        yield client


@pytest.fixture
def forwarded(_fake_proxy: _FakeProxy) -> list[Forwarded]:
    """What the proxy forwarded to the app since this test's `socket_client`
    opened, in order."""
    return _fake_proxy.forwarded
