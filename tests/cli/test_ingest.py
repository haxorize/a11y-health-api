import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.cli._operations import AppNotFoundError, ingest
from a11y_health.cli._scan import (
    EmptyScanDirectoryError,
    MalformedScanFileError,
    MissingScanDirectoryError,
    NameResolutionError,
    UnderivableAppNameError,
    UnparseableScanTimestampError,
)
from a11y_health.models.enums import ScanRunStatus
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
    assert len(resp.json()) == 2


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
    assert len(resp.json()) == 2


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


async def test_ingest_unparseable_scan_timestamp_names_the_file(no_server: AsyncClient, tmp_path: Path) -> None:
    write_scan_file(tmp_path, "a.json", name="foo.com", end_time="last Tuesday")

    with pytest.raises(UnparseableScanTimestampError) as exc_info:
        await ingest(no_server, directory=tmp_path)

    message = str(exc_info.value)
    assert "a.json" in message
    assert "last Tuesday" in message


async def test_ingest_non_string_scan_timestamp_names_the_file(no_server: AsyncClient, tmp_path: Path) -> None:
    # The one caller that justifies `write_scan_file`'s untyped `end_time`.
    write_scan_file(tmp_path, "a.json", name="foo.com", end_time=1_700_000_000)

    with pytest.raises(UnparseableScanTimestampError) as exc_info:
        await ingest(no_server, directory=tmp_path)

    assert "a.json" in str(exc_info.value)


async def test_ingest_falls_back_to_directory_mtime_when_no_endtime(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    await make_app_with_org_unit(db_session, slug="foo-com")

    payload = make_axe_payload(name="foo.com", url="https://example.com/a")
    payload.pop("endTime", None)
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
    await make_app_with_org_unit(db_session, slug="foo-com")

    write_scan_file(tmp_path, "a.json", name="foo.com", url="https://example.com/a")

    malformed = {"name": "foo.com", "endTime": "2026-03-30T11:55:52-0400"}
    (tmp_path / "b.json").write_text(json.dumps(malformed))

    result = await ingest(db_client, directory=tmp_path)

    assert result.pages_uploaded == 1
    assert len(result.errors) == 1
    assert "b.json" in result.errors[0]
    # The Error Contract's code, not the bare status — the code names the mode, and
    # the mode is what the operator has to act on.
    assert "invalid_axe_payload" in result.errors[0]

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
    # Not valid UTF-8. `read_text` raises UnicodeDecodeError, a ValueError subclass
    # that would otherwise escape the loader as a traceback.
    (tmp_path / "binary.json").write_bytes(b'{"name": "\xff\xfe"}')

    with pytest.raises(MalformedScanFileError) as exc_info:
        await ingest(no_server, directory=tmp_path)

    message = str(exc_info.value)
    assert "binary.json" in message
    # Says what actually failed: these bytes never reached the JSON parser.
    assert "UTF-8" in message


async def test_ingest_overlong_app_name_reports_the_length_bound(no_server: AsyncClient, tmp_path: Path) -> None:
    # The named error forwards derive_slug's own wording, so the operator learns
    # which derivation rule the name broke rather than a flattened "underivable".
    write_scan_file(tmp_path, "a.json", name="a" * 256)

    with pytest.raises(UnderivableAppNameError, match="longer than 255 characters"):
        await ingest(no_server, directory=tmp_path)


async def test_ingest_non_object_scan_file_names_the_file(no_server: AsyncClient, tmp_path: Path) -> None:
    # Valid JSON, wrong document: an export that wrapped its page in a list. The
    # bytes parse, so the decode guard never fires and the loader would go on to
    # call .get() on a list.
    (tmp_path / "wrapped.json").write_text('[{"name": "foo.com"}]')

    with pytest.raises(MalformedScanFileError) as exc_info:
        await ingest(no_server, directory=tmp_path)

    message = str(exc_info.value)
    assert "wrapped.json" in message
    assert "object" in message


async def test_ingest_underivable_app_name_names_the_file(no_server: AsyncClient, tmp_path: Path) -> None:
    # Every other load failure names its file; across a 30-directory import this is
    # the difference between a fixable report and a hunt.
    write_scan_file(tmp_path, "offender.json", name="!!!")

    with pytest.raises(UnderivableAppNameError) as exc_info:
        await ingest(no_server, directory=tmp_path)

    assert "offender.json" in str(exc_info.value)
