"""The API surface this tool speaks to — one function per request it makes.

This module owns every request, the failures only a server answer can produce,
and the API prefix. It never reads a directory and never prints; give it a
client and it gives you back what the server said. Each function here is one
call, and sequencing them belongs to `_operations`. This module and `_scan`
never import each other, and no import-graph test holds that line: ADR 0043
records why it is load-bearing, with the rest of the package's split.

There is deliberately no port abstraction over the transport. `httpx`'s own
transport *is* the seam, and it already has two real adapters, not one:
production runs over `AsyncHTTPTransport` against a deployed server, and the
suite runs over both, `ASGITransport` against the real app and a real database
in the command suites, and `AsyncHTTPTransport` against the app on a real port
in `tests/cli/test_live_server.py`. Its stub, `MockTransport`, carries this
module's own suite — the decode and transport-failure cases no server produces
on cue. A hand-rolled protocol in front of that would add an interface with one
implementation and buy no test that the adapters don't already give.
"""

from datetime import datetime
from typing import Any

import httpx

from a11y_health.cli._errors import CliError
from a11y_health.core.error_body import read_error_body
from a11y_health.models.enums import ScanRunStatus

# The API this tool speaks is versioned in its path, and no caller has ever had
# a reason to address a different one — the host varies (--base-url), the
# contract does not.
_API_PREFIX = "/api/v1"


def make_client(base_url: str) -> httpx.AsyncClient:
    """The one client this tool speaks through, so what the socket suite
    drives is what `a11y` ships: httpx's defaults, no redirect following, no
    transport override. Any header, timeout, or limit the tool adopts is set
    here and nowhere else."""
    return httpx.AsyncClient(base_url=base_url)


class ApiUnreachableError(CliError):
    def __init__(self, base_url: str, reason: httpx.RequestError) -> None:
        self.base_url = base_url
        self.reason = reason
        # Several httpx transport errors stringify to nothing, which would
        # leave the sentence with a hole in it — fall back to naming the class.
        super().__init__(
            f"Could not reach the API at {base_url}: {reason or type(reason).__name__}. "
            "Check that the server is running and that --base-url points at it."
        )


class ApiTimeoutError(CliError):
    def __init__(self, base_url: str, reason: httpx.TimeoutException) -> None:
        self.base_url = base_url
        self.reason = reason
        super().__init__(
            f"The API at {base_url} timed out ({type(reason).__name__}). The server answered the "
            "connection but not the request in time — it may be slow under load. A request that "
            "timed out may still have been applied."
        )


class UnreadableApiResponseError(CliError):
    def __init__(self, path: str, status: int, reason: ValueError) -> None:
        self.path = path
        self.status = status
        self.reason = reason
        super().__init__(
            f"The API answered {path} with {status}, but the body is not JSON this tool can read: "
            f"{reason}. Check that --base-url points at the a11y-health API and not another server."
        )


class ApiError(CliError):
    def __init__(self, *, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


async def _send(client: httpx.AsyncClient, method: str, path: str, **kwargs: Any) -> httpx.Response:
    """Every request the CLI makes, so the API prefix is applied in one place
    and a transport failure — server down, wrong host, DNS, timeout — becomes
    one named error instead of an httpx traceback at each call site."""
    try:
        return await client.request(method, f"{_API_PREFIX}{path}", **kwargs)
    except httpx.TimeoutException as exc:
        # Checked before RequestError, which it subclasses: a live-but-slow
        # server is a different diagnosis from an absent one, and needs a
        # different fix.
        raise ApiTimeoutError(str(client.base_url), exc) from exc
    except httpx.RequestError as exc:
        raise ApiUnreachableError(str(client.base_url), exc) from exc


async def _request(
    client: httpx.AsyncClient, method: str, path: str, *, allow: tuple[int, ...] = (), **kwargs: Any
) -> httpx.Response:
    """`_send`, with any unsuccessful status the caller didn't `allow` raised
    as the API's own coded error — so no operation has to remember the check,
    and one that forgets it can't fall through to decoding an error body as a
    result."""
    resp = await _send(client, method, path, **kwargs)
    if not resp.is_success and resp.status_code not in allow:
        raise _api_error(resp)
    return resp


def _json(resp: httpx.Response) -> Any:
    """The decoded body of a response that already passed its status check. A
    success status carrying an unreadable body means `--base-url` names
    something that isn't this API — the operator's to fix, so it fails as a
    named error rather than as a `ValueError` escaping `main()` into a
    traceback."""
    try:
        return resp.json()
    except ValueError as exc:
        raise UnreadableApiResponseError(resp.request.url.path, resp.status_code, exc) from exc


# Enough of a proxy's page or a stack trace to recognize it by.
_RAW_BODY_LIMIT = 500


def _api_error(resp: httpx.Response) -> ApiError:
    coded = read_error_body(resp.content)
    if coded is None:
        # Not the contract's shape — a framework 422, a proxy's HTML. The status
        # and raw body still tell the operator something; a traceback would not.
        text = resp.text
        if len(text) > _RAW_BODY_LIMIT:
            text = f"{text[:_RAW_BODY_LIMIT]}… ({len(text) - _RAW_BODY_LIMIT} more characters)"
        return ApiError(code=str(resp.status_code), message=text)
    return ApiError(code=coded.code, message=coded.message)


async def find_app_by_slug(client: httpx.AsyncClient, slug: str) -> dict | None:
    """The App carrying this Slug, or `None` when the server has none.

    The only non-success status this module hands back instead of raising: both
    callers have something to do with an absent App, and neither treats it as a
    failure of the request.
    """
    resp = await _request(client, "GET", f"/apps/slug/{slug}", allow=(404,))
    return None if resp.status_code == 404 else _json(resp)


async def create_app(client: httpx.AsyncClient, *, name: str, brand_id: int, org_unit_id: int) -> int:
    resp = await _request(
        client, "POST", "/apps", json={"name": name, "brand_id": brand_id, "org_unit_id": org_unit_id}
    )
    return _json(resp)["id"]


async def create_scan_run(client: httpx.AsyncClient, *, app_id: int, scanned_at: datetime) -> int:
    resp = await _request(client, "POST", f"/apps/{app_id}/scan-runs", json={"scanned_at": scanned_at.isoformat()})
    return _json(resp)["id"]


async def upload_page(client: httpx.AsyncClient, *, scan_run_id: int, payload: dict) -> ApiError | None:
    """`None` when the page was accepted, the coded rejection when it wasn't.

    Returned rather than raised: one unacceptable page must not strand the pages
    behind it, and the caller decides what a partial run means.
    """
    resp = await _send(client, "POST", f"/scan-runs/{scan_run_id}/pages", json=payload)
    return None if resp.is_success else _api_error(resp)


async def complete_scan_run(client: httpx.AsyncClient, *, scan_run_id: int) -> None:
    await _request(client, "PATCH", f"/scan-runs/{scan_run_id}", json={"status": ScanRunStatus.COMPLETED.value})


async def list_org_units(client: httpx.AsyncClient) -> list[dict]:
    return _json(await _request(client, "GET", "/org-units"))


async def list_brands(client: httpx.AsyncClient) -> list[dict]:
    return _json(await _request(client, "GET", "/brands"))


async def create_org_unit(client: httpx.AsyncClient, *, name: str, parent_id: int | None = None) -> int:
    return _json(await _request(client, "POST", "/org-units", json={"name": name, "parent_id": parent_id}))["id"]
