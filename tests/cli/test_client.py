from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from a11y_health.cli import _client
from a11y_health.cli._client import ApiError, ApiUnreachableError, UnreadableApiResponseError, list_brands
from a11y_health.cli._errors import CliError
from a11y_health.cli._operations import ingest
from tests.factories import write_scan_file


async def _brands_error(handler: Callable[[httpx.Request], httpx.Response]) -> ApiError:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://test") as client:
        with pytest.raises(ApiError) as exc_info:
            await list_brands(client)
    return exc_info.value


async def test_unknown_error_code_still_renders_code_and_message() -> None:
    # A server deployed ahead of this CLI can answer with a code the CLI has
    # never heard of. The decode stays open so that code still reaches the
    # operator.
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"code": "a_mode_added_after_this_release", "message": "cannot proceed"})

    error = await _brands_error(handler)

    assert error.code == "a_mode_added_after_this_release"
    assert error.message == "cannot proceed"
    assert str(error) == "a_mode_added_after_this_release: cannot proceed"


async def test_body_that_is_not_the_coded_shape_falls_back_to_raw_text() -> None:
    # The framework's own 422 carries `detail`, not the contract's two fields.
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(422, json={"detail": [{"loc": ["body"], "msg": "field required"}]})

    error = await _brands_error(handler)

    assert error.code == "422"
    assert "field required" in error.message


async def test_body_that_is_not_json_at_all_falls_back_to_raw_text() -> None:
    # A proxy or load balancer answering instead of the app.
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="<html><body>Bad Gateway</body></html>")

    error = await _brands_error(handler)

    assert error.code == "502"
    assert "Bad Gateway" in error.message


async def test_raw_body_fallback_is_bounded() -> None:
    # A proxy can answer with a whole page, or a stack trace. The operator
    # needs the start of it, not a terminal's worth.
    body = "<html>" + "x" * 20_000 + "TAIL</html>"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text=body)

    error = await _brands_error(handler)

    assert error.message.startswith("<html>xxx")
    assert "TAIL" not in error.message
    assert len(error.message) < len(body) // 10


@pytest.mark.parametrize(("extra", "truncated"), [(0, False), (1, True)])
async def test_raw_body_fallback_bound_starts_one_past_the_limit(extra: int, truncated: bool) -> None:
    body = "x" * (_client._RAW_BODY_LIMIT + extra)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text=body)

    error = await _brands_error(handler)

    assert (error.message != body) is truncated


async def test_raw_body_fallback_keeps_the_limit_and_counts_the_rest() -> None:
    body = "x" * (_client._RAW_BODY_LIMIT + 1)

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text=body)

    error = await _brands_error(handler)

    assert error.message == "x" * 500 + "… (1 more characters)"


async def test_unreachable_api_fails_as_an_operator_error() -> None:
    # The server isn't up, or --base-url is wrong. Both are the operator's to
    # fix, so neither should arrive as an httpx traceback.
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://localhost:8000") as client:
        with pytest.raises(ApiUnreachableError) as exc_info:
            await list_brands(client)

    message = str(exc_info.value)
    assert "http://localhost:8000" in message
    assert "--base-url" in message


async def test_success_body_that_is_not_json_fails_as_an_operator_error() -> None:
    # --base-url pointed at something that answers 200 with HTML: the UI dev
    # server, or an SSO portal. Wrong address is the operator's to fix, so the
    # decode failure must not escape as the raw ValueError that `main()` no
    # longer catches.
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>login</html>")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://localhost:3000") as client:
        with pytest.raises(UnreadableApiResponseError) as exc_info:
            await list_brands(client)

    # The class, not `CliError`: `ApiUnreachableError` also names --base-url,
    # so a handler raising it instead would pass a message-only check.
    error = exc_info.value
    assert (error.path, error.status) == ("/api/v1/brands", 200)
    assert "--base-url" in str(error)


async def test_timeout_is_reported_as_a_timeout_not_as_a_dead_server() -> None:
    # A slow-but-healthy server is not an absent one, and httpx's timeout
    # exceptions stringify to nothing — so the reason has to come from
    # somewhere else.
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://localhost:8000") as client:
        with pytest.raises(CliError) as exc_info:
            await list_brands(client)

    message = str(exc_info.value)
    assert "timed out" in message
    assert "Check that the server is running" not in message
    # `str(httpx.ReadTimeout(""))` is empty, so the kind of timeout has to be
    # named from the exception's type or the operator learns nothing about the
    # failure.
    assert "ReadTimeout" in message


async def test_transport_failure_mid_upload_names_the_pending_scan_run(tmp_path: Path) -> None:
    # The run is already created when the connection drops, so it is left
    # Pending exactly like a partial page failure — and needs the same "delete
    # run N" pointer.
    write_scan_file(tmp_path, "a.json", name="foo.com")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/pages"):
            raise httpx.ConnectError("connection refused", request=request)
        if request.url.path.endswith("/scan-runs"):
            return httpx.Response(201, json={"id": 7})
        return httpx.Response(200, json={"id": 1})

    messages: list[str] = []
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://localhost:8000") as client:
        with pytest.raises(ApiUnreachableError):
            await ingest(client, directory=tmp_path, on_progress=messages.append)

    assert any("7" in m and "delete run" in m for m in messages), messages
