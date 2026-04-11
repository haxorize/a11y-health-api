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


def _is_date_dir(name: str) -> bool:
    try:
        datetime.strptime(name, "%Y-%m-%d")
    except ValueError:
        return False
    return True


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


@dataclass
class BulkImportResult:
    app_id: int
    app_created: bool
    upload_results: list[UploadResult] = field(default_factory=list)


def _find_date_dirs(directory: Path) -> list[Path]:
    return sorted(d for d in directory.iterdir() if d.is_dir() and _is_date_dir(d.name))


async def bulk_import(
    client: httpx.AsyncClient,
    *,
    directory: Path,
    org_unit_id: int,
    brand: str,
    api_prefix: str = "/api/v1",
    on_progress: ProgressCallback | None = None,
) -> BulkImportResult:
    report = on_progress or _noop
    slug = directory.name

    resp = await client.get(f"{api_prefix}/apps/slug/{slug}")
    if resp.status_code == 404:
        resp = await client.post(
            f"{api_prefix}/apps",
            json={"name": slug, "slug": slug, "brand": brand, "org_unit_id": org_unit_id},
        )
        resp.raise_for_status()
        app_id = resp.json()["id"]
        app_created = True
        report(f"Created app '{slug}' (id={app_id})")
    else:
        resp.raise_for_status()
        app_id = resp.json()["id"]
        app_created = False
        report(f"Found existing app '{slug}' (id={app_id})")

    date_dirs = _find_date_dirs(directory)

    result = BulkImportResult(app_id=app_id, app_created=app_created)
    for date_dir in date_dirs:
        report(f"Processing {date_dir.name}")
        upload_result = await upload_scan(
            client,
            app_id=app_id,
            directory=date_dir,
            api_prefix=api_prefix,
            on_progress=on_progress,
        )
        result.upload_results.append(upload_result)

    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload axe DevTools scan results")
    subparsers = parser.add_subparsers(dest="command", required=True)

    upload_parser = subparsers.add_parser("upload", help="Upload a single scan directory")
    upload_parser.add_argument("app_id", type=int, help="Application ID")
    upload_parser.add_argument("directory", type=Path, help="Directory containing axe JSON files")
    upload_parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")

    bulk_parser = subparsers.add_parser("bulk", help="Bulk import from app directory with date subdirectories")
    bulk_parser.add_argument("directory", type=Path, help="App directory containing date subdirectories")
    bulk_parser.add_argument("--org-unit-id", type=int, required=True, help="Org unit ID for auto-created apps")
    bulk_parser.add_argument("--brand", required=True, help="Brand for auto-created apps")
    bulk_parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")

    args = parser.parse_args()

    if args.command == "upload":

        async def _run_upload() -> UploadResult:
            async with httpx.AsyncClient(base_url=args.base_url) as client:
                return await upload_scan(client, app_id=args.app_id, directory=args.directory, on_progress=print)

        result = asyncio.run(_run_upload())
        if result.errors:
            for error in result.errors:
                print(f"  ERROR: {error}")
            sys.exit(1)

    elif args.command == "bulk":

        async def _run_bulk() -> BulkImportResult:
            async with httpx.AsyncClient(base_url=args.base_url) as client:
                return await bulk_import(
                    client,
                    directory=args.directory,
                    org_unit_id=args.org_unit_id,
                    brand=args.brand,
                    on_progress=print,
                )

        bulk_result = asyncio.run(_run_bulk())
        errors = [e for r in bulk_result.upload_results for e in r.errors]
        if errors:
            for error in errors:
                print(f"  ERROR: {error}")
            sys.exit(1)
