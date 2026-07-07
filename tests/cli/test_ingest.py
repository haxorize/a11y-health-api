import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.cli import AppNotFoundError, NameResolutionError, ingest
from a11y_health.models.enums import ScanRunStatus
from tests.factories import make_app_with_org_unit, make_axe_payload


def _write_scan_file(directory: Path, filename: str, *, name: str, url: str) -> None:
    payload = make_axe_payload(name=name, url=url)
    payload["endTime"] = "2026-03-30T11:55:52-0400"
    (directory / filename).write_text(json.dumps(payload))


async def test_ingest_creates_completed_scan_run_for_existing_app(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    test_app = await make_app_with_org_unit(db_session, slug="foo-com")

    for i, url in enumerate(["https://example.com/page1", "https://example.com/page2"]):
        _write_scan_file(tmp_path, f"page{i}.json", name="foo.com", url=url)

    result = await ingest(db_client, directory=tmp_path)

    assert result.app_id == test_app.id
    assert result.app_slug == "foo-com"

    resp = await db_client.get(f"/api/v1/scan-runs/{result.scan_run_id}")
    assert resp.status_code == 200
    assert resp.json()["status"] == ScanRunStatus.COMPLETED.value

    resp = await db_client.get(f"/api/v1/scan-runs/{result.scan_run_id}/pages")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_ingest_missing_or_empty_name_hard_fails(db_client: AsyncClient, tmp_path: Path) -> None:
    _write_scan_file(tmp_path, "a.json", name="foo.com", url="https://example.com/a")

    no_name = make_axe_payload(url="https://example.com/b")
    del no_name["name"]
    (tmp_path / "b_no_name.json").write_text(json.dumps(no_name))

    empty_name = make_axe_payload(name="", url="https://example.com/c")
    (tmp_path / "c_empty_name.json").write_text(json.dumps(empty_name))

    with pytest.raises(NameResolutionError) as exc_info:
        await ingest(db_client, directory=tmp_path)

    message = str(exc_info.value)
    assert "b_no_name.json" in message
    assert "c_empty_name.json" in message


async def test_ingest_name_mismatch_hard_fails_before_network_call(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:
    await make_app_with_org_unit(db_session, slug="foo-com")

    _write_scan_file(tmp_path, "a.json", name="foo.com", url="https://example.com/a")
    _write_scan_file(tmp_path, "b.json", name="bar.com", url="https://example.com/b")

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
    _write_scan_file(tmp_path, "a.json", name="FOO.COM", url="https://foo.com/a")
    _write_scan_file(tmp_path, "b.json", name="foo.com", url="https://foo.com/b")

    result = await ingest(db_client, directory=tmp_path)

    assert result.app_id == test_app.id
    assert result.app_slug == "foo-com"

    resp = await db_client.get(f"/api/v1/scan-runs/{result.scan_run_id}/pages")
    assert len(resp.json()) == 2


async def test_ingest_missing_app_fails_with_import_pointer(db_client: AsyncClient, tmp_path: Path) -> None:
    _write_scan_file(tmp_path, "a.json", name="unknown.com", url="https://example.com/a")

    with pytest.raises(AppNotFoundError) as exc_info:
        await ingest(db_client, directory=tmp_path)

    message = str(exc_info.value)
    assert "unknown.com" in message
    assert "a11y import" in message


async def test_ingest_name_deriving_to_empty_slug_fails_loudly(db_client: AsyncClient, tmp_path: Path) -> None:
    _write_scan_file(tmp_path, "a.json", name="!!!", url="https://example.com/a")

    with pytest.raises(ValueError, match="empty slug"):
        await ingest(db_client, directory=tmp_path)


async def test_ingest_missing_directory_raises(db_client: AsyncClient, tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"

    with pytest.raises(ValueError, match="Directory does not exist"):
        await ingest(db_client, directory=missing)


async def test_ingest_empty_directory_raises(db_client: AsyncClient, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="No JSON files found"):
        await ingest(db_client, directory=tmp_path)


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

    _write_scan_file(tmp_path, "a.json", name="foo.com", url="https://example.com/a")

    malformed = {"name": "foo.com", "endTime": "2026-03-30T11:55:52-0400"}
    (tmp_path / "b.json").write_text(json.dumps(malformed))

    result = await ingest(db_client, directory=tmp_path)

    assert result.pages_uploaded == 1
    assert len(result.errors) == 1
    assert "b.json" in result.errors[0]
    assert "400" in result.errors[0]

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
        _write_scan_file(tmp_path, f"page{i}.json", name="foo.com", url=f"https://example.com/page{i}")

    messages: list[str] = []
    result = await ingest(db_client, directory=tmp_path, on_progress=messages.append)

    first_upload = next(i for i, m in enumerate(messages) if "page0.json" in m and "Upload" in m)
    resolved_idx = next(i for i, m in enumerate(messages) if "foo-com" in m and str(test_app.id) in m)
    scan_run_idx = next(i for i, m in enumerate(messages) if str(result.scan_run_id) in m)

    assert resolved_idx < first_upload
    assert scan_run_idx < first_upload
