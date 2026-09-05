"""The CLI over a real socket: `AsyncHTTPTransport`, the adapter production
runs, against the app served by uvicorn on an ephemeral port. Every other CLI
suite runs in-process over `ASGITransport`; this one covers the failures only
a socket produces. The server and the fake proxy in front of it are
`live_server` in conftest."""

from pathlib import Path

import httpx
import pytest
from httpx import AsyncClient

from a11y_health.cli._client import ApiError, ApiTimeoutError, list_brands
from a11y_health.cli._operations import import_app, ingest
from a11y_health.models.enums import ScanRunStatus
from tests.cli.conftest import (
    PROXY_BODY_LIMIT,
    PROXY_BODY_LIMIT_BYTES,
    PROXY_HEADER,
    PROXY_REDIRECT,
    PROXY_STALL,
    Forwarded,
)
from tests.factories import (
    SessionFactory,
    make_app_with_org_unit,
    make_brand,
    make_org_unit,
    write_scan_dir,
    write_scan_file,
)

pytestmark = pytest.mark.integration


async def test_ingest_over_a_real_socket_creates_a_completed_scan_run(
    committed_session_factory: SessionFactory,
    socket_client: AsyncClient,
    forwarded: list[Forwarded],
    tmp_path: Path,
) -> None:
    async with committed_session_factory() as db:
        test_app = await make_app_with_org_unit(db, slug="foo-com")
        await db.commit()

    for i in range(3):
        write_scan_file(tmp_path, f"page{i}.json", name="foo.com", url=f"https://example.com/page{i}")

    result = await ingest(socket_client, directory=tmp_path)
    on_the_wire = list(forwarded)

    assert result.app_id == test_app.id
    assert result.pages_uploaded == 3

    # One ingest is one connection (#137): a client that reconnected per page
    # would arrive from a fresh ephemeral port each time.
    uploads = [f for f in on_the_wire if f.method == "POST" and f.path.endswith("/pages")]
    assert len(uploads) == 3
    assert len({f.peer for f in on_the_wire}) == 1

    # What the CLI relies on crossing the socket unaltered (#137): the server
    # parses a page only when the body is declared JSON, and the CLI decodes
    # every body it reads as JSON, so the shipped client (`make_client`) may
    # not narrow Accept past JSON, and nothing may hand back another type.
    for upload in uploads:
        assert upload.request_headers["content-type"] == "application/json"
        assert upload.request_headers["accept"] in ("*/*", "application/json")
    assert {f.response_headers["content-type"] for f in on_the_wire} == {"application/json"}

    resp = await socket_client.get(f"/api/v1/scan-runs/{result.scan_run_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == ScanRunStatus.COMPLETED.value
    # Only the socket server sets this; ASGITransport never does, so a client
    # quietly handed a transport override again fails here.
    assert resp.headers["server"] == "uvicorn"


async def test_import_over_a_real_socket_creates_the_app_and_one_scan_run_per_date(
    committed_session_factory: SessionFactory,
    socket_client: AsyncClient,
    forwarded: list[Forwarded],
    tmp_path: Path,
) -> None:
    async with committed_session_factory() as db:
        org_unit = await make_org_unit(db)
        brand = await make_brand(db)
        await db.commit()

    for date in ["2026-03-30", "2026-04-01"]:
        write_scan_dir(tmp_path, date, name="foo.com")

    result = await import_app(socket_client, directory=tmp_path, org_unit_id=org_unit.id, brand_id=brand.id)
    on_the_wire = list(forwarded)

    assert result.app_created is True
    assert len(result.ingest_results) == 2
    # An import is several ingests on one connection (#137): the socket-only
    # claim here is reuse *across* them, not within one.
    uploads = [f for f in on_the_wire if f.method == "POST" and f.path.endswith("/pages")]
    assert len(uploads) == 2
    assert len({f.peer for f in on_the_wire}) == 1
    resp = await socket_client.get(f"/api/v1/apps/{result.app_id}")
    assert resp.status_code == 200
    assert resp.json()["slug"] == "foo-com"
    assert resp.headers["server"] == "uvicorn"
    for ingest_result in result.ingest_results:
        resp = await socket_client.get(f"/api/v1/scan-runs/{ingest_result.scan_run_id}")
        assert resp.json()["status"] == ScanRunStatus.COMPLETED.value


async def test_read_timeout_on_a_real_socket_is_the_cli_timeout_error(socket_client: AsyncClient) -> None:
    # Connect succeeds; the proxy holds the response past the read timeout.
    socket_client.headers[PROXY_HEADER] = PROXY_STALL
    socket_client.timeout = httpx.Timeout(5.0, read=0.05)

    with pytest.raises(ApiTimeoutError) as exc_info:
        await list_brands(socket_client)

    assert isinstance(exc_info.value.reason, httpx.ReadTimeout)
    assert str(socket_client.base_url).rstrip("/") in str(exc_info.value)


async def test_redirect_on_a_real_socket_is_the_cli_coded_error_not_a_followed_request(
    socket_client: AsyncClient,
) -> None:
    socket_client.headers[PROXY_HEADER] = PROXY_REDIRECT

    with pytest.raises(ApiError) as exc_info:
        await list_brands(socket_client)

    assert exc_info.value.code == "307"


async def test_large_post_rejected_by_a_proxy_is_one_failed_page_and_the_run_continues(
    committed_session_factory: SessionFactory,
    socket_client: AsyncClient,
    forwarded: list[Forwarded],
    tmp_path: Path,
) -> None:
    # A size-capped ingress answers 413 before the body is read and closes the
    # connection (#140). The CLI must report that page as its own coded error
    # with the proxy's text, reconnect, and carry the pages behind it.
    async with committed_session_factory() as db:
        await make_app_with_org_unit(db, slug="foo-com")
        await db.commit()

    write_scan_file(tmp_path, "small.json", name="foo.com", url="https://example.com/small")
    write_scan_file(
        tmp_path, "large.json", name="foo.com", url="https://example.com/" + "p" * (2 * PROXY_BODY_LIMIT_BYTES)
    )
    socket_client.headers[PROXY_HEADER] = PROXY_BODY_LIMIT

    result = await ingest(socket_client, directory=tmp_path)
    on_the_wire = list(forwarded)

    assert result.pages_uploaded == 1
    assert result.errors == ["large.json: 413: <html><body>Request Entity Too Large</body></html>"]
    resp = await socket_client.get(f"/api/v1/scan-runs/{result.scan_run_id}")
    assert resp.json()["status"] == ScanRunStatus.PENDING.value

    # The rejected upload never reached the app, and the proxy's close cost
    # the CLI one reconnect, not the run: the requests after it arrive on a
    # fresh peer.
    uploads = [f for f in on_the_wire if f.method == "POST" and f.path.endswith("/pages")]
    assert len(uploads) == 1
    assert len({f.peer for f in on_the_wire}) == 2
