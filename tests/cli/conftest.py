from collections.abc import AsyncIterator

import httpx
import pytest


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
