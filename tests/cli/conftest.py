import asyncio
from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest
import uvicorn
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from a11y_health.core import database
from tests.conftest import honest_app
from tests.factories import SessionFactory


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
# shutdown; `redirect` bounces to a real route.
PROXY_HEADER = b"x-test-proxy"
PROXY_STALL = "stall"
PROXY_REDIRECT = "redirect"


class _FakeProxy:
    def __init__(self, inner: Any) -> None:
        self.inner = inner

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        behavior = dict(scope["headers"]).get(PROXY_HEADER) if scope["type"] == "http" else None
        if behavior == PROXY_STALL.encode():
            while (await receive())["type"] != "http.disconnect":
                pass
        elif behavior == PROXY_REDIRECT.encode():
            await send({"type": "http.response.start", "status": 307, "headers": [(b"location", b"/api/v1/brands")]})
            await send({"type": "http.response.body", "body": b""})
        else:
            await self.inner(scope, receive, send)


@pytest.fixture(scope="session")
async def live_server() -> AsyncIterator[str]:
    """The real app on a real port, as the base URL a client with no transport
    override reaches it at.

    uvicorn runs as a task on the suite's session loop rather than in a thread
    or a subprocess, so the served app shares the test process's patched
    sessionmaker and the Declaration Honesty request scope (ADR 0033). Over a
    socket an undeclared mode surfaces as the server's 500 rather than as the
    shim's assertion text. Lifespan is off, as it is under `ASGITransport`: the
    app's lifespan pings the dev `DATABASE_URL`, and the suite requires only
    the test database.
    """
    config = uvicorn.Config(_FakeProxy(honest_app), host="127.0.0.1", port=0, lifespan="off", log_level="warning")
    server = uvicorn.Server(config)
    serving = asyncio.create_task(server.serve())
    async with asyncio.timeout(5):
        while not server.started:
            if serving.done():
                serving.result()
            await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await serving


@pytest.fixture
async def socket_client(live_server: str) -> AsyncIterator[httpx.AsyncClient]:
    """A client on the CLI's own `AsyncHTTPTransport` against `live_server`,
    for the requests the fake proxy answers before any database is reached."""
    async with httpx.AsyncClient(base_url=live_server) as client:
        yield client


@pytest.fixture
async def http_client(
    socket_client: httpx.AsyncClient,
    engine: AsyncEngine,
    committed_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> httpx.AsyncClient:
    """`socket_client` with the served app's requests on real-commit sessions
    from the test engine: the production `get_db`, bound to the test engine
    the way `test_rollup_deadlock.py` binds it, since a server's requests
    cannot join a test's rolled-back transaction. `committed_session_factory`
    is here for its truncate at teardown (ADR 0011)."""
    monkeypatch.setattr(database, "async_session", async_sessionmaker(engine, expire_on_commit=False))
    return socket_client
