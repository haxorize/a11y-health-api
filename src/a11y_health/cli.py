"""CLI tool for uploading axe DevTools scan results."""

import argparse
import asyncio
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

from a11y_health.models.scan_run import ScanRunStatus

ProgressCallback = Callable[[str], None]


def _noop(_msg: str) -> None:
    pass


@dataclass
class UploadResult:
    scan_run_id: int
    pages_uploaded: int
    errors: list[str] = field(default_factory=list)


def _parse_scanned_at(payloads: list[dict], directory: Path) -> datetime:
    for payload in payloads:
        if end_time := payload.get("endTime"):
            return datetime.fromisoformat(end_time)
    mtime = directory.stat().st_mtime
    return datetime.fromtimestamp(mtime, tz=UTC)


def _load_directory(directory: Path) -> tuple[list[Path], list[dict], datetime]:
    if not directory.is_dir():
        raise ValueError(f"Directory does not exist: {directory}")

    json_files = sorted(directory.glob("*.json"))
    if not json_files:
        raise ValueError(f"No JSON files found in {directory}")

    payloads = [json.loads(f.read_text()) for f in json_files]
    scanned_at = _parse_scanned_at(payloads, directory)
    return json_files, payloads, scanned_at


async def upload_scan(
    client: httpx.AsyncClient,
    *,
    app_id: int,
    directory: Path,
    api_prefix: str = "/api/v1",
    on_progress: ProgressCallback | None = None,
) -> UploadResult:
    json_files, payloads, scanned_at = _load_directory(directory)

    report = on_progress or _noop
    report(f"Found {len(json_files)} JSON files in {directory}")

    resp = await client.post(
        f"{api_prefix}/apps/{app_id}/scan-runs",
        json={"scanned_at": scanned_at.isoformat()},
    )
    resp.raise_for_status()
    scan_run_id = resp.json()["id"]
    report(f"Created scan run {scan_run_id}")

    errors: list[str] = []
    pages_uploaded = 0
    for file, payload in zip(json_files, payloads, strict=True):
        resp = await client.post(
            f"{api_prefix}/scan-runs/{scan_run_id}/pages",
            json=payload,
        )
        if resp.is_success:
            pages_uploaded += 1
            report(f"Uploaded {file.name}")
        else:
            error = f"{file.name}: {resp.status_code} {resp.text}"
            errors.append(error)
            report(f"Failed {file.name}: {resp.status_code}")

    resp = await client.patch(
        f"{api_prefix}/scan-runs/{scan_run_id}",
        json={"status": ScanRunStatus.COMPLETED.value},
    )
    resp.raise_for_status()
    report(f"Scan run {scan_run_id} completed: {pages_uploaded} pages uploaded")

    return UploadResult(scan_run_id=scan_run_id, pages_uploaded=pages_uploaded, errors=errors)


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload axe DevTools scan results")
    parser.add_argument("app_id", type=int, help="Application ID")
    parser.add_argument("directory", type=Path, help="Directory containing axe JSON files")
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")
    args = parser.parse_args()

    async def _run() -> UploadResult:
        async with httpx.AsyncClient(base_url=args.base_url) as client:
            return await upload_scan(client, app_id=args.app_id, directory=args.directory, on_progress=print)

    result = asyncio.run(_run())
    if result.errors:
        for error in result.errors:
            print(f"  ERROR: {error}")
        sys.exit(1)
