"""Data import / ingest CLI.

Pick by app state:
- `a11y import <dir> --org-unit-id <id> --brand-id <id>` onboards a new app from a
  directory of YYYY-MM-DD subdirectories. Creates the app if missing, reuses if not.
  `--name` sets the display name at creation (must be derivation-equivalent to the
  axe JSON name; identity is locked once created).
- `a11y ingest <dir>` uploads a single scan to an existing app. Errors with a pointer
  to `import` if the app isn't registered.
"""

import argparse
import asyncio
import json
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

from a11y_health.core.slug import derive_slug
from a11y_health.models.enums import ScanRunStatus

ProgressCallback = Callable[[str], None]


def _is_date_dir(name: str) -> bool:
    try:
        datetime.strptime(name, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _noop(_msg: str) -> None:
    pass


def _parse_scanned_at(payloads: list[dict], directory: Path) -> datetime:
    for payload in payloads:
        if end_time := payload.get("endTime"):
            return datetime.fromisoformat(end_time)
    mtime = directory.stat().st_mtime
    return datetime.fromtimestamp(mtime, tz=UTC)


def _split_by_date_dir(directory: Path) -> tuple[list[Path], list[Path]]:
    date_dirs: list[Path] = []
    skipped: list[Path] = []
    for entry in sorted(directory.iterdir()):
        if entry.is_dir() and _is_date_dir(entry.name):
            date_dirs.append(entry)
        else:
            skipped.append(entry)
    return date_dirs, skipped


@dataclass
class LoadedScan:
    directory: Path
    files: list[Path]
    payloads: list[dict]
    scanned_at: datetime


def _load_scan(directory: Path) -> LoadedScan:
    if not directory.is_dir():
        raise ValueError(f"Directory does not exist: {directory}")

    files = sorted(directory.glob("*.json"))
    if not files:
        raise ValueError(f"No JSON files found in {directory}")

    payloads = [json.loads(f.read_text()) for f in files]
    scanned_at = _parse_scanned_at(payloads, directory)
    return LoadedScan(directory=directory, files=files, payloads=payloads, scanned_at=scanned_at)


class AppNotFoundError(Exception):
    def __init__(self, name: str, slug: str) -> None:
        self.name = name
        self.slug = slug
        super().__init__(
            f"App with slug {slug!r} (derived from axe JSON name {name!r}) not found. "
            "Run `a11y import <dir> --org-unit-id <id> --brand-id <id>` to onboard a new app."
        )


class NameOverrideMismatchError(Exception):
    def __init__(self, *, name: str, json_name: str) -> None:
        self.name = name
        self.json_name = json_name
        super().__init__(
            f"--name {name!r} derives to slug {derive_slug(name)!r}, but the axe JSON name {json_name!r} "
            f"derives to {derive_slug(json_name)!r}. The override must derive to the same slug, "
            "or future imports of this directory would resolve to a different App."
        )


class NoDateDirsError(Exception):
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        super().__init__(
            f"No YYYY-MM-DD subdirectories found in {directory}. "
            "Run `a11y ingest <dir>` to upload a single scan to an existing app."
        )


class NameResolutionError(Exception):
    def __init__(
        self,
        *,
        missing: list[Path] | None = None,
        conflicts: dict[str, list[Path]] | None = None,
    ) -> None:
        self.missing: list[Path] = missing or []
        self.conflicts: dict[str, list[Path]] = conflicts or {}
        parts: list[str] = []
        if self.missing:
            files = ", ".join(f.name for f in self.missing)
            parts.append(f"missing or empty 'name' in: {files}")
        if self.conflicts:
            detail = "; ".join(
                f"{name!r} in [{', '.join(str(f) for f in files)}]" for name, files in self.conflicts.items()
            )
            parts.append(f"conflicting names: {detail}")
        super().__init__("; ".join(parts) or "name resolution failed")


def _resolve_app_name(scans: list[LoadedScan]) -> str:
    missing: list[Path] = []
    by_name: dict[str, list[Path]] = {}
    for scan in scans:
        for file, payload in zip(scan.files, scan.payloads, strict=True):
            name = payload.get("name")
            if not isinstance(name, str) or not name:
                missing.append(file)
                continue
            by_name.setdefault(name, []).append(file)

    conflicts = by_name if len(by_name) > 1 else {}
    if missing or conflicts:
        raise NameResolutionError(missing=missing, conflicts=conflicts)
    return next(iter(by_name))


@dataclass
class IngestResult:
    app_id: int
    app_slug: str
    scan_run_id: int
    pages_uploaded: int
    errors: list[str] = field(default_factory=list)


async def _upload_scan(
    client: httpx.AsyncClient,
    *,
    app_id: int,
    app_slug: str,
    scan: LoadedScan,
    api_prefix: str,
    on_progress: ProgressCallback,
) -> IngestResult:
    resp = await client.post(
        f"{api_prefix}/apps/{app_id}/scan-runs",
        json={"scanned_at": scan.scanned_at.isoformat()},
    )
    resp.raise_for_status()
    scan_run_id = resp.json()["id"]
    on_progress(f"Created scan run {scan_run_id}")

    errors: list[str] = []
    pages_uploaded = 0
    for file, payload in zip(scan.files, scan.payloads, strict=True):
        resp = await client.post(
            f"{api_prefix}/scan-runs/{scan_run_id}/pages",
            json=payload,
        )
        if resp.is_success:
            pages_uploaded += 1
            on_progress(f"Uploaded {file.name}")
        else:
            errors.append(f"{file.name}: {resp.status_code} {resp.text}")
            on_progress(f"Failed {file.name}: {resp.status_code}")

    resp = await client.patch(
        f"{api_prefix}/scan-runs/{scan_run_id}",
        json={"status": ScanRunStatus.COMPLETED.value},
    )
    resp.raise_for_status()
    on_progress(f"Scan run {scan_run_id} completed: {pages_uploaded} pages uploaded")

    return IngestResult(
        app_id=app_id,
        app_slug=app_slug,
        scan_run_id=scan_run_id,
        pages_uploaded=pages_uploaded,
        errors=errors,
    )


async def ingest(
    client: httpx.AsyncClient,
    *,
    directory: Path,
    api_prefix: str = "/api/v1",
    on_progress: ProgressCallback = _noop,
) -> IngestResult:
    scan = _load_scan(directory)
    on_progress(f"Found {len(scan.files)} JSON files in {directory}")

    name = _resolve_app_name([scan])
    slug = derive_slug(name)

    resp = await client.get(f"{api_prefix}/apps/slug/{slug}")
    if resp.status_code == 404:
        raise AppNotFoundError(name, slug)
    resp.raise_for_status()
    app_id = resp.json()["id"]
    on_progress(f"Resolved app '{slug}' (id={app_id})")

    return await _upload_scan(
        client,
        app_id=app_id,
        app_slug=slug,
        scan=scan,
        api_prefix=api_prefix,
        on_progress=on_progress,
    )


@dataclass
class ImportResult:
    app_id: int
    app_slug: str
    app_created: bool
    ingest_results: list[IngestResult] = field(default_factory=list)


async def import_app(
    client: httpx.AsyncClient,
    *,
    directory: Path,
    org_unit_id: int,
    brand_id: int,
    name: str | None = None,
    api_prefix: str = "/api/v1",
    on_progress: ProgressCallback = _noop,
) -> ImportResult:
    date_dirs, skipped = _split_by_date_dir(directory)
    if not date_dirs:
        raise NoDateDirsError(directory)
    if skipped:
        on_progress(f"Skipping non-date entries: {', '.join(e.name for e in skipped)}")

    scans = [_load_scan(d) for d in date_dirs]
    json_name = _resolve_app_name(scans)
    slug = derive_slug(json_name)

    resp = await client.get(f"{api_prefix}/apps/slug/{slug}")
    if resp.status_code == 404:
        # Equivalence is only enforced when the override actually names the App;
        # on an existing App the override is ignored below, mismatched or not (AC10).
        if name is not None and derive_slug(name) != slug:
            raise NameOverrideMismatchError(name=name, json_name=json_name)
        resp = await client.post(
            f"{api_prefix}/apps",
            json={"name": name or json_name, "brand_id": brand_id, "org_unit_id": org_unit_id},
        )
        resp.raise_for_status()
        app_id = resp.json()["id"]
        app_created = True
        on_progress(f"Created app '{slug}' (id={app_id})")
    else:
        resp.raise_for_status()
        existing = resp.json()
        app_id = existing["id"]
        app_created = False
        on_progress(f"Found existing app '{slug}' (id={app_id})")
        if name is not None and name != existing["name"]:
            on_progress(
                f"--name {name!r} ignored: identity is locked at creation and the app "
                f"already exists as {existing['name']!r}"
            )

    ingest_results: list[IngestResult] = []
    for scan in scans:
        on_progress(f"Processing {scan.directory.name}")
        ingest_results.append(
            await _upload_scan(
                client,
                app_id=app_id,
                app_slug=slug,
                scan=scan,
                api_prefix=api_prefix,
                on_progress=on_progress,
            )
        )

    return ImportResult(app_id=app_id, app_slug=slug, app_created=app_created, ingest_results=ingest_results)


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload axe DevTools scan results")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Upload a single scan directory")
    ingest_parser.add_argument("directory", type=Path, help="Directory containing axe JSON files")
    ingest_parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")

    import_parser = subparsers.add_parser("import", help="Onboard an app from a directory of date subdirectories")
    import_parser.add_argument("directory", type=Path, help="App directory containing YYYY-MM-DD subdirectories")
    import_parser.add_argument("--org-unit-id", type=int, required=True, help="Org unit ID for the onboarded app")
    import_parser.add_argument("--brand-id", type=int, required=True, help="Brand ID for the onboarded app")
    import_parser.add_argument(
        "--name",
        default=None,
        help="Display name for the app on first import; must derive to the same slug as the axe JSON name",
    )
    import_parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")

    args = parser.parse_args()

    if args.command == "ingest":

        async def _run_ingest() -> IngestResult:
            async with httpx.AsyncClient(base_url=args.base_url) as client:
                return await ingest(client, directory=args.directory, on_progress=print)

        ingest_result = asyncio.run(_run_ingest())
        if ingest_result.errors:
            for error in ingest_result.errors:
                print(f"  ERROR: {error}")
            sys.exit(1)

    elif args.command == "import":

        async def _run_import() -> ImportResult:
            async with httpx.AsyncClient(base_url=args.base_url) as client:
                return await import_app(
                    client,
                    directory=args.directory,
                    org_unit_id=args.org_unit_id,
                    brand_id=args.brand_id,
                    name=args.name,
                    on_progress=print,
                )

        import_result = asyncio.run(_run_import())
        errors = [e for r in import_result.ingest_results for e in r.errors]
        if errors:
            for error in errors:
                print(f"  ERROR: {error}")
            sys.exit(1)
