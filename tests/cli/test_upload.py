import json
import os
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.cli import upload_scan
from a11y_health.models.enums import ScanRunStatus
from tests.factories import make_app_with_org_unit, make_axe_payload


async def test_upload_creates_completed_scan_run(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:

    test_app = await make_app_with_org_unit(db_session)

    # Write two axe JSON files into tmp_path
    for i, url in enumerate(["https://example.com/page1", "https://example.com/page2"]):
        payload = make_axe_payload(url=url, violations=[])
        payload["endTime"] = "2026-03-30T11:55:52-0400"
        (tmp_path / f"page{i}.json").write_text(json.dumps(payload))

    result = await upload_scan(db_client, app_id=test_app.id, directory=tmp_path)

    # Scan run was created and completed
    resp = await db_client.get(f"/api/v1/scan-runs/{result.scan_run_id}")
    assert resp.status_code == 200
    scan_run = resp.json()
    assert scan_run["status"] == ScanRunStatus.COMPLETED.value

    # Both pages were uploaded
    resp = await db_client.get(f"/api/v1/scan-runs/{result.scan_run_id}/pages")
    assert resp.status_code == 200
    assert len(resp.json()) == 2


async def test_scanned_at_from_end_time(db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path) -> None:

    test_app = await make_app_with_org_unit(db_session)

    payload = make_axe_payload(url="https://example.com")
    payload["endTime"] = "2026-03-30T11:55:52-0400"
    (tmp_path / "page.json").write_text(json.dumps(payload))

    result = await upload_scan(db_client, app_id=test_app.id, directory=tmp_path)

    resp = await db_client.get(f"/api/v1/scan-runs/{result.scan_run_id}")
    scan_run = resp.json()
    # endTime was -0400, which is UTC-4 → 15:55:52 UTC
    assert scan_run["scanned_at"] == "2026-03-30T15:55:52Z"


async def test_scanned_at_falls_back_to_directory_mtime(
    db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path
) -> None:

    test_app = await make_app_with_org_unit(db_session)

    # Payload with no endTime
    payload = make_axe_payload(url="https://example.com")
    (tmp_path / "page.json").write_text(json.dumps(payload))

    # Set a known mtime on the directory
    fixed_ts = datetime(2026, 2, 15, 10, 30, 0, tzinfo=UTC).timestamp()
    os.utime(tmp_path, (fixed_ts, fixed_ts))

    result = await upload_scan(db_client, app_id=test_app.id, directory=tmp_path)

    resp = await db_client.get(f"/api/v1/scan-runs/{result.scan_run_id}")
    scan_run = resp.json()
    assert scan_run["scanned_at"] == "2026-02-15T10:30:00Z"


async def test_reports_progress(db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path) -> None:

    test_app = await make_app_with_org_unit(db_session)

    for i in range(3):
        payload = make_axe_payload(url=f"https://example.com/page{i}")
        payload["endTime"] = "2026-03-30T11:55:52-0400"
        (tmp_path / f"page{i}.json").write_text(json.dumps(payload))

    messages: list[str] = []
    result = await upload_scan(db_client, app_id=test_app.id, directory=tmp_path, on_progress=messages.append)

    assert result.pages_uploaded == 3
    # Should report starting with file count, then each file
    assert any("3 JSON" in m for m in messages)
    assert any("page0.json" in m for m in messages)
    assert any("page1.json" in m for m in messages)
    assert any("page2.json" in m for m in messages)


async def test_error_on_empty_directory(db_client: AsyncClient, tmp_path: Path) -> None:

    with pytest.raises(ValueError, match="No JSON files"):
        await upload_scan(db_client, app_id=1, directory=tmp_path)


async def test_error_on_nonexistent_directory(db_client: AsyncClient) -> None:

    with pytest.raises(ValueError, match="does not exist"):
        await upload_scan(db_client, app_id=1, directory=Path("/nonexistent/path"))


async def test_error_on_invalid_app_id(db_client: AsyncClient, tmp_path: Path) -> None:

    payload = make_axe_payload(url="https://example.com")
    payload["endTime"] = "2026-03-30T11:55:52-0400"
    (tmp_path / "page.json").write_text(json.dumps(payload))

    with pytest.raises(httpx.HTTPStatusError, match="404"):
        await upload_scan(db_client, app_id=999999, directory=tmp_path)


async def test_continues_on_partial_failure(db_session: AsyncSession, db_client: AsyncClient, tmp_path: Path) -> None:

    test_app = await make_app_with_org_unit(db_session)

    # Valid file
    good = make_axe_payload(url="https://example.com/good")
    good["endTime"] = "2026-03-30T11:55:52-0400"
    (tmp_path / "a_good.json").write_text(json.dumps(good))

    # Invalid axe payload (missing required fields)
    (tmp_path / "b_bad.json").write_text(json.dumps({"not": "valid"}))

    # Another valid file
    good2 = make_axe_payload(url="https://example.com/good2")
    good2["endTime"] = "2026-03-30T11:55:52-0400"
    (tmp_path / "c_good2.json").write_text(json.dumps(good2))

    result = await upload_scan(db_client, app_id=test_app.id, directory=tmp_path)

    assert result.pages_uploaded == 2
    assert len(result.errors) == 1
    assert "b_bad.json" in result.errors[0]
