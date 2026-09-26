import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import AsyncClient, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.cli import _client
from a11y_health.cli._operations import AppNotFoundError, ingest
from a11y_health.cli._scan import (
    EmptyScanDirectoryError,
    InvalidScanFilesError,
    MalformedScanFileError,
    MissingScanDirectoryError,
    NameResolutionError,
    UnderivableAppNameError,
)
from a11y_health.models.enums import ScanRunStatus
from a11y_health.models.page_result import PageResult
from tests.factories import make_app_with_org_unit, make_axe_payload, write_scan_file


async def test_ingest_creates_completed_scan_run_for_existing_app(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    test_app = await make_app_with_org_unit(db_session, slug="foo-com")

    for i, url in enumerate(["https://example.com/page1", "https://example.com/page2"]):
        write_scan_file(tmp_path, f"page{i}.json", name="foo.com", url=url)

    result = await ingest(db_client, directory=tmp_path)

    assert result.app_id == test_app.id
    assert result.app_slug == "foo-com"

    resp = await db_client.get(f"/api/v1/scan-runs/{result.scan_run_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == ScanRunStatus.COMPLETED.value

    resp = await db_client.get(f"/api/v1/scan-runs/{result.scan_run_id}/pages")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 2


async def test_ingest_missing_or_empty_name_hard_fails(no_server: AsyncClient, tmp_path: Path) -> None:
    write_scan_file(tmp_path, "a.json", name="foo.com", url="https://example.com/a")

    no_name = make_axe_payload(url="https://example.com/b")
    del no_name["name"]
    (tmp_path / "b_no_name.json").write_text(json.dumps(no_name))

    empty_name = make_axe_payload(name="", url="https://example.com/c")
    (tmp_path / "c_empty_name.json").write_text(json.dumps(empty_name))

    with pytest.raises(NameResolutionError) as exc_info:
        await ingest(no_server, directory=tmp_path)

    message = str(exc_info.value)
    assert "b_no_name.json" in message
    assert "c_empty_name.json" in message


async def test_ingest_name_mismatch_hard_fails_before_network_call(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    await make_app_with_org_unit(db_session, slug="foo-com")

    write_scan_file(tmp_path, "a.json", name="foo.com", url="https://example.com/a")
    write_scan_file(tmp_path, "b.json", name="bar.com", url="https://example.com/b")

    with pytest.raises(NameResolutionError) as exc_info:
        await ingest(db_client, directory=tmp_path)

    message = str(exc_info.value)
    assert "foo.com" in message
    assert "bar.com" in message
    # Reported by slug — the unit that actually makes them distinct Apps.
    assert "foo-com" in message
    assert "bar-com" in message

    resp = await db_client.get("/api/v1/apps/slug/foo-com")
    assert resp.json()["id"]
    resp = await db_client.get(f"/api/v1/apps/{resp.json()['id']}/scan-runs")
    assert resp.json()["items"] == []


async def test_ingest_same_slug_variants_resolve_one_app(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    test_app = await make_app_with_org_unit(db_session, slug="foo-com")

    # Casing drift between pages of one scan; both names derive to foo-com.
    write_scan_file(tmp_path, "a.json", name="FOO.COM", url="https://foo.com/a")
    write_scan_file(tmp_path, "b.json", name="foo.com", url="https://foo.com/b")

    result = await ingest(db_client, directory=tmp_path)

    assert result.app_id == test_app.id
    assert result.app_slug == "foo-com"

    resp = await db_client.get(f"/api/v1/scan-runs/{result.scan_run_id}/pages")
    assert len(resp.json()["items"]) == 2


async def test_ingest_missing_app_fails_with_import_pointer(db_client: AsyncClient, tmp_path: Path) -> None:
    write_scan_file(tmp_path, "a.json", name="unknown.com", url="https://example.com/a")

    with pytest.raises(AppNotFoundError) as exc_info:
        await ingest(db_client, directory=tmp_path)

    message = str(exc_info.value)
    assert "unknown.com" in message
    assert "a11y import" in message


async def test_ingest_name_deriving_to_empty_slug_fails_loudly(no_server: AsyncClient, tmp_path: Path) -> None:
    write_scan_file(tmp_path, "a.json", name="!!!", url="https://example.com/a")

    with pytest.raises(UnderivableAppNameError, match="empty slug"):
        await ingest(no_server, directory=tmp_path)


async def test_ingest_missing_directory_raises(no_server: AsyncClient, tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"

    with pytest.raises(MissingScanDirectoryError, match="Directory does not exist"):
        await ingest(no_server, directory=missing)


async def test_ingest_empty_directory_raises(no_server: AsyncClient, tmp_path: Path) -> None:
    with pytest.raises(EmptyScanDirectoryError, match="No JSON files found"):
        await ingest(no_server, directory=tmp_path)


async def test_ingest_malformed_scan_file_names_the_file(no_server: AsyncClient, tmp_path: Path) -> None:
    write_scan_file(tmp_path, "good.json", name="foo.com", url="https://example.com/a")
    (tmp_path / "truncated.json").write_text('{"name": "foo.com"')

    with pytest.raises(MalformedScanFileError) as exc_info:
        await ingest(no_server, directory=tmp_path)

    assert "truncated.json" in str(exc_info.value)


@pytest.mark.parametrize("end_time", [1_700_000_000, "last Tuesday"])
async def test_ingest_unreadable_scan_timestamp_names_the_file_and_field(
    no_server: AsyncClient, tmp_path: Path, end_time: object
) -> None:
    # Names the field and the format it wanted, never the value: echoing an
    # untrusted document's bytes back into an operator line is a reflection
    # finding, and the operator has the file to look in.
    write_scan_file(tmp_path, "a.json", name="foo.com", end_time=end_time)

    with pytest.raises(InvalidScanFilesError) as exc_info:
        await ingest(no_server, directory=tmp_path)

    message = str(exc_info.value)
    assert "a.json" in message
    assert "endTime" in message
    assert "ISO 8601" in message


async def test_ingest_schema_invalid_scan_file_fails_before_any_upload(no_server: AsyncClient, tmp_path: Path) -> None:
    # The headline operator-visible change of moving the crossing into the
    # CLI: a file the server would reject fails here, at load, so no Scan Run
    # is created and nothing is left pending. `no_server` is the proof, and
    # the good file sorting first shows a load doesn't stop at the first
    # success.
    write_scan_file(tmp_path, "a.json", name="foo.com", url="https://example.com/a")
    broken = make_axe_payload(name="foo.com", url="https://example.com/b")
    del broken["findings"]
    (tmp_path / "b.json").write_text(json.dumps(broken))

    with pytest.raises(InvalidScanFilesError) as exc_info:
        await ingest(no_server, directory=tmp_path)

    message = str(exc_info.value)
    assert "b.json" in message
    assert "findings" in message
    # The guidance names what ran, leads with fixing the file, and names the
    # one remedy for version skew — a reinstall, not a bypass flag. Pinned
    # whole, since each plural sentence contains its singular's opening words.
    assert message.startswith("1 scan file failed axe schema validation: ")
    assert message.endswith(
        ". Fix the file; if this server accepts it as-is, the CLI and server are different versions: "
        "reinstall a11y-health at the server's version."
    )


async def test_ingest_reports_every_invalid_scan_file_at_once(no_server: AsyncClient, tmp_path: Path) -> None:
    # One re-run fixes everything: the load doesn't stop at the first invalid
    # file, and the message names each one with its own reason.
    write_scan_file(tmp_path, "a.json", name="foo.com", end_time="last Tuesday")
    write_scan_file(tmp_path, "b.json", name="foo.com", url="https://example.com/b")
    broken = make_axe_payload(name="foo.com", url="https://example.com/c")
    del broken["findings"]
    (tmp_path / "c.json").write_text(json.dumps(broken))

    with pytest.raises(InvalidScanFilesError) as exc_info:
        await ingest(no_server, directory=tmp_path)

    assert [path.name for path, _ in exc_info.value.failures] == ["a.json", "c.json"]
    message = str(exc_info.value)
    assert message.startswith("2 scan files failed axe schema validation: ")
    assert message.endswith(
        ". Fix the files; if this server accepts them as-is, the CLI and server are different versions: "
        "reinstall a11y-health at the server's version."
    )
    assert "a.json" in message and "endTime" in message
    assert "c.json" in message and "findings" in message
    assert "b.json" not in message


async def test_ingest_uploads_the_document_exactly_as_read(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    # Reds when the upload sends the model's own dump instead of the decoded
    # document kept beside it: the unmodeled key would be gone from Raw JSON.
    await make_app_with_org_unit(db_session, slug="foo-com")
    document = make_axe_payload(
        name="foo.com",
        url="https://example.com/a",
        end_time="2026-03-30T11:55:52-0400",
        unmodeled={"toolVersion": "4.10.2"},
    )
    (tmp_path / "a.json").write_text(json.dumps(document))

    result = await ingest(db_client, directory=tmp_path)

    stored = await db_session.scalar(select(PageResult.raw_json).where(PageResult.scan_run_id == result.scan_run_id))
    assert stored == document


async def test_ingest_falls_back_to_directory_mtime_when_no_endtime(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    await make_app_with_org_unit(db_session, slug="foo-com")

    payload = make_axe_payload(name="foo.com", url="https://example.com/a")
    file = tmp_path / "a.json"
    file.write_text(json.dumps(payload))

    expected_ts = 1_700_000_000.0
    os.utime(tmp_path, (expected_ts, expected_ts))

    result = await ingest(db_client, directory=tmp_path)

    resp = await db_client.get(f"/api/v1/scan-runs/{result.scan_run_id}")
    assert resp.status_code == 200
    assert datetime.fromisoformat(resp.json()["scanned_at"]) == datetime.fromtimestamp(expected_ts, tz=UTC)


async def test_ingest_records_per_page_upload_failures(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    # A rejection only the server can make: every file loads locally, and the
    # run is completed out from under the CLI after its first page lands, so
    # the second page meets `scan_run_completed`. (A malformed file no longer
    # reaches the server — it fails at load, the test above.)
    await make_app_with_org_unit(db_session, slug="foo-com")
    write_scan_file(tmp_path, "a.json", name="foo.com", url="https://example.com/a")
    write_scan_file(tmp_path, "b.json", name="foo.com", url="https://example.com/b")

    # The hook neither removes itself (httpx is iterating that list while it
    # runs) nor asserts (a failure inside a hook surfaces as a traceback out of
    # `_upload_scan`, not as this test's assertion): it fires once, records
    # the PATCH status, and the checks happen after `ingest` returns.
    completion_status: list[int] = []

    async def complete_after_first_page(response: Response) -> None:
        request: Request = response.request
        if completion_status or not (
            request.method == "POST" and request.url.path.endswith("/pages") and response.status_code == 201
        ):
            return
        scan_run_id = request.url.path.split("/")[-2]
        completed = await db_client.patch(f"/api/v1/scan-runs/{scan_run_id}", json={"status": "completed"})
        completion_status.append(completed.status_code)

    db_client.event_hooks["response"].append(complete_after_first_page)
    messages: list[str] = []
    try:
        result = await ingest(db_client, directory=tmp_path, on_progress=messages.append)
    finally:
        db_client.event_hooks["response"].remove(complete_after_first_page)

    assert completion_status == [200]
    assert result.pages_uploaded == 1
    assert len(result.errors) == 1
    assert "b.json" in result.errors[0]
    # The Error Contract's code, not the bare status — the code names the mode,
    # and the mode is what the operator has to act on.
    assert "scan_run_completed" in result.errors[0]

    # The CLI never completes a partial run itself: it reports the run as left
    # pending, by id, for the operator to fix and delete.
    assert any(f"Scan run {result.scan_run_id} left pending" in m for m in messages)
    assert not any(m.startswith(f"Scan run {result.scan_run_id} completed") for m in messages)


async def test_ingest_leaves_a_partial_run_pending_and_unscored(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The test above's rejection is server-made, but making it completes the
    # run, so it cannot pin what the CLI leaves behind. Here the second page's
    # rejection is faked at the client seam and the server is never told, so
    # the run's state is exactly what the CLI left it in.
    await make_app_with_org_unit(db_session, slug="foo-com")
    write_scan_file(tmp_path, "a.json", name="foo.com", url="https://example.com/a")
    write_scan_file(tmp_path, "b.json", name="foo.com", url="https://example.com/b")

    real_upload_page = _client.upload_page
    calls = 0

    async def reject_second_page(client: AsyncClient, *, scan_run_id: int, payload: dict) -> _client.ApiError | None:
        nonlocal calls
        calls += 1
        if calls == 1:
            return await real_upload_page(client, scan_run_id=scan_run_id, payload=payload)
        return _client.ApiError(code="invalid_axe_payload", message="faked at the client seam")

    monkeypatch.setattr(_client, "upload_page", reject_second_page)
    messages: list[str] = []
    result = await ingest(db_client, directory=tmp_path, on_progress=messages.append)

    assert result.pages_uploaded == 1
    assert len(result.errors) == 1

    # A partial run is left Pending (unscored), never completed over a subset.
    resp = await db_client.get(f"/api/v1/scan-runs/{result.scan_run_id}")
    assert resp.json()["status"] == "pending"
    summary = await db_client.get(f"/api/v1/scan-runs/{result.scan_run_id}/summary")
    assert summary.status_code == 404


async def test_ingest_reports_resolved_app_and_scan_run_before_uploading_pages(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    test_app = await make_app_with_org_unit(db_session, slug="foo-com")

    for i in range(2):
        write_scan_file(tmp_path, f"page{i}.json", name="foo.com", url=f"https://example.com/page{i}")

    messages: list[str] = []
    result = await ingest(db_client, directory=tmp_path, on_progress=messages.append)

    first_upload = next(i for i, m in enumerate(messages) if "page0.json" in m and "Upload" in m)
    resolved_idx = next(i for i, m in enumerate(messages) if "foo-com" in m and str(test_app.id) in m)
    scan_run_idx = next(i for i, m in enumerate(messages) if str(result.scan_run_id) in m)

    assert resolved_idx < first_upload
    assert scan_run_idx < first_upload


async def test_ingest_undecodable_scan_file_names_the_file(no_server: AsyncClient, tmp_path: Path) -> None:
    # Not valid UTF-8. `read_text` raises UnicodeDecodeError, a ValueError
    # subclass that would otherwise escape the loader as a traceback.
    (tmp_path / "binary.json").write_bytes(b'{"name": "\xff\xfe"}')

    with pytest.raises(MalformedScanFileError) as exc_info:
        await ingest(no_server, directory=tmp_path)

    message = str(exc_info.value)
    assert "binary.json" in message
    # Says what actually failed: these bytes never reached the JSON parser.
    assert "UTF-8" in message


async def test_ingest_overlong_app_name_reports_the_length_bound(no_server: AsyncClient, tmp_path: Path) -> None:
    # The named error forwards derive_slug's own wording, so the operator
    # learns which derivation rule the name broke rather than a flattened
    # "underivable".
    write_scan_file(tmp_path, "a.json", name="a" * 256)

    with pytest.raises(UnderivableAppNameError, match="longer than 255 characters"):
        await ingest(no_server, directory=tmp_path)


async def test_ingest_non_object_scan_file_names_the_file(no_server: AsyncClient, tmp_path: Path) -> None:
    # Valid JSON, wrong document: an export that wrapped its page in a list. The
    # bytes parse, so the decode guard never fires; the axe boundary refuses it.
    (tmp_path / "wrapped.json").write_text('[{"name": "foo.com"}]')

    with pytest.raises(InvalidScanFilesError) as exc_info:
        await ingest(no_server, directory=tmp_path)

    message = str(exc_info.value)
    assert "wrapped.json" in message
    assert "not a JSON object" in message


async def test_ingest_underivable_app_name_names_the_file(no_server: AsyncClient, tmp_path: Path) -> None:
    # Every other load failure names its file; across a 30-directory import
    # this is the difference between a fixable report and a hunt.
    write_scan_file(tmp_path, "offender.json", name="!!!")

    with pytest.raises(UnderivableAppNameError) as exc_info:
        await ingest(no_server, directory=tmp_path)

    assert "offender.json" in str(exc_info.value)
