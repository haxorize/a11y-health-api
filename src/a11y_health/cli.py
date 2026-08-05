"""App onboarding CLI.

Pick by task:
- `a11y org-units list` / `a11y brands list` print id + name tables (org units also
  show their parent) — use them to find the `--org-unit-id` / `--brand-id` that
  `import` needs.
- `a11y org-units create <name> [--parent-id <id>]` creates a missing org unit and
  prints its id, so onboarding never has to leave the CLI.
- `a11y import <dir> --org-unit-id <id> --brand-id <id>` onboards a new app from a
  directory of YYYY-MM-DD subdirectories. Creates the app if missing, reuses if not.
  `--name` sets the display name at creation (must be derivation-equivalent to the
  axe JSON name; identity is locked once created).
- `a11y ingest <dir>` uploads a single scan to an existing app. Errors with a pointer
  to `import` if the app isn't registered.

Other admin mutations (app move/rename/delete, org-unit reparent/delete) stay on
Swagger `/docs`.
"""

import argparse
import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

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
            parsed = datetime.fromisoformat(end_time)
            # An offset-less endTime is otherwise uncomparable against the UTC mtime
            # fallback and against sibling scans (import orders scans by scanned_at) — assume UTC.
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
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


class CliError(Exception):
    """Base for expected, operator-facing CLI failures. `main()` prints these as
    a single `ERROR:` line and exits non-zero instead of dumping a traceback."""


class AppNotFoundError(CliError):
    def __init__(self, name: str, slug: str) -> None:
        self.name = name
        self.slug = slug
        super().__init__(
            f"App with slug {slug!r} (derived from axe JSON name {name!r}) not found. "
            "Run `a11y import <dir> --org-unit-id <id> --brand-id <id>` to onboard a new app."
        )


class NameOverrideMismatchError(CliError):
    def __init__(self, *, name: str, json_name: str) -> None:
        self.name = name
        self.json_name = json_name
        super().__init__(
            f"--name {name!r} derives to slug {derive_slug(name)!r}, but the axe JSON name {json_name!r} "
            f"derives to {derive_slug(json_name)!r}. The override must derive to the same slug, "
            "or future imports of this directory would resolve to a different App."
        )


class NoDateDirsError(CliError):
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        super().__init__(
            f"No YYYY-MM-DD subdirectories found in {directory}. "
            "Run `a11y ingest <dir>` to upload a single scan to an existing app."
        )


class NameVariant(NamedTuple):
    name: str
    file: Path


class NameResolutionError(CliError):
    def __init__(
        self,
        *,
        missing: list[Path] | None = None,
        conflicts: dict[str, list[NameVariant]] | None = None,
    ) -> None:
        self.missing: list[Path] = missing or []
        # slug -> the name variants that derived to it — keyed on slug because the
        # slug is the unit of collision; same-slug variants never reach here.
        self.conflicts: dict[str, list[NameVariant]] = conflicts or {}
        parts: list[str] = []
        if self.missing:
            files = ", ".join(f.name for f in self.missing)
            parts.append(f"missing or empty 'name' in: {files}")
        if self.conflicts:
            detail = "; ".join(
                f"{slug} from {', '.join(sorted({repr(v.name) for v in variants}))} "
                f"in [{', '.join(str(v.file) for v in variants)}]"
                for slug, variants in self.conflicts.items()
            )
            parts.append(f"conflicting slugs: {detail}")
        super().__init__("; ".join(parts) or "name resolution failed")


class ApiError(CliError):
    def __init__(self, *, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def _resolve_app_name(scans: list[LoadedScan]) -> str:
    # Identity is the derived slug (ADR 0019), so names that differ only in
    # presentation but derive to the same slug are the same App — not a conflict.
    # A genuine conflict is two distinct slugs. Among same-slug variants the display
    # name is cosmetic; the newest scan's variant (by observation time) wins — equal
    # scanned_at ties fall to first-seen, harmless because the pick is cosmetic.
    missing: list[Path] = []
    by_slug: dict[str, list[NameVariant]] = {}
    underivable: list[str] = []
    newest_name: str | None = None
    newest_at: datetime | None = None
    for scan in scans:
        for file, payload in zip(scan.files, scan.payloads, strict=True):
            name = payload.get("name")
            if not isinstance(name, str) or not name:
                missing.append(file)
                continue
            try:
                slug = derive_slug(name)
            except ValueError:
                # An unslugifiable name still fails loudly, but only after the
                # structured missing/conflict report below — never pre-empting it.
                underivable.append(name)
                continue
            by_slug.setdefault(slug, []).append(NameVariant(name, file))
            if newest_at is None or scan.scanned_at > newest_at:
                newest_at, newest_name = scan.scanned_at, name

    conflicts = by_slug if len(by_slug) > 1 else {}
    if missing or conflicts:
        raise NameResolutionError(missing=missing, conflicts=conflicts)
    if underivable:
        derive_slug(underivable[0])  # re-raise the ValueError for the unslugifiable name
    assert newest_name is not None  # exactly one slug ⇒ at least one present name
    return newest_name


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
    if not resp.is_success:
        raise _api_error(resp)
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

    if errors:
        # A partial run must not be scored: completing it would snapshot a score
        # over whatever subset happened to upload. Leave it Pending (unscored),
        # so the operator can fix the inputs and re-ingest, then delete it.
        on_progress(
            f"Scan run {scan_run_id} left pending: {len(errors)} of {len(scan.files)} pages failed — "
            f"fix the inputs and re-ingest, then delete run {scan_run_id}"
        )
    else:
        resp = await client.patch(
            f"{api_prefix}/scan-runs/{scan_run_id}",
            json={"status": ScanRunStatus.COMPLETED.value},
        )
        if not resp.is_success:
            raise _api_error(resp)
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
    if not resp.is_success:
        raise _api_error(resp)
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
        if not resp.is_success:
            raise _api_error(resp)
        app_id = resp.json()["id"]
        app_created = True
        on_progress(f"Created app '{slug}' (id={app_id})")
    else:
        if not resp.is_success:
            raise _api_error(resp)
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


async def list_org_units(client: httpx.AsyncClient, *, api_prefix: str = "/api/v1") -> list[dict]:
    resp = await client.get(f"{api_prefix}/org-units")
    if not resp.is_success:
        raise _api_error(resp)
    return resp.json()


async def list_brands(client: httpx.AsyncClient, *, api_prefix: str = "/api/v1") -> list[dict]:
    resp = await client.get(f"{api_prefix}/brands")
    if not resp.is_success:
        raise _api_error(resp)
    return resp.json()


def _api_error(resp: httpx.Response) -> ApiError:
    # Surface the Error Contract's coded body ({"code", "message"}); fall back to raw text for
    # non-coded failures (e.g. a framework 422) so a caller still gets a message, not a traceback.
    try:
        body = resp.json()
        return ApiError(code=body["code"], message=body["message"])
    except json.JSONDecodeError, KeyError, TypeError:
        return ApiError(code=str(resp.status_code), message=resp.text)


async def create_org_unit(
    client: httpx.AsyncClient, *, name: str, parent_id: int | None = None, api_prefix: str = "/api/v1"
) -> int:
    resp = await client.post(f"{api_prefix}/org-units", json={"name": name, "parent_id": parent_id})
    if not resp.is_success:
        raise _api_error(resp)
    return resp.json()["id"]


def _print_table(rows: list[dict], columns: list[str]) -> None:
    print("\t".join(col.upper() for col in columns))
    for row in rows:
        print("\t".join("-" if row.get(col) is None else str(row[col]) for col in columns))


def _add_base_url(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-url", default="http://localhost:8000", help="API base URL")


def _run[T](base_url: str, call: Callable[[httpx.AsyncClient], Awaitable[T]]) -> T:
    async def _main() -> T:
        async with httpx.AsyncClient(base_url=base_url) as client:
            return await call(client)

    return asyncio.run(_main())


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload axe DevTools scan results")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_parser = subparsers.add_parser("ingest", help="Upload a single scan directory")
    ingest_parser.add_argument("directory", type=Path, help="Directory containing axe JSON files")
    _add_base_url(ingest_parser)

    import_parser = subparsers.add_parser("import", help="Onboard an app from a directory of date subdirectories")
    import_parser.add_argument("directory", type=Path, help="App directory containing YYYY-MM-DD subdirectories")
    import_parser.add_argument("--org-unit-id", type=int, required=True, help="Org unit ID for the onboarded app")
    import_parser.add_argument("--brand-id", type=int, required=True, help="Brand ID for the onboarded app")
    import_parser.add_argument(
        "--name",
        default=None,
        help="Display name for the app on first import; must derive to the same slug as the axe JSON name",
    )
    _add_base_url(import_parser)

    org_units_parser = subparsers.add_parser("org-units", help="List or create org units")
    org_units_sub = org_units_parser.add_subparsers(dest="subcommand", required=True)
    ou_list = org_units_sub.add_parser("list", help="List all org units (id, name, parent)")
    _add_base_url(ou_list)
    ou_create = org_units_sub.add_parser("create", help="Create an org unit and print its id")
    ou_create.add_argument("name", help="Display name for the new org unit")
    ou_create.add_argument("--parent-id", type=int, default=None, help="Parent org unit id (omit for a root)")
    _add_base_url(ou_create)

    brands_parser = subparsers.add_parser("brands", help="List brands")
    brands_sub = brands_parser.add_subparsers(dest="subcommand", required=True)
    brands_list = brands_sub.add_parser("list", help="List all brands (id, name)")
    _add_base_url(brands_list)

    args = parser.parse_args()

    # Every operator-facing failure prints one clean `ERROR:` line and exits
    # non-zero: coded API errors (ApiError) and local input errors alike — an
    # unregistered app, a missing/empty scan dir, no date subdirs, a name
    # conflict, or an unslugifiable name, which surface as CliError or (from
    # `_load_scan`/`derive_slug`) ValueError. Only per-page upload failures are
    # handled inline, since a partial ingest still returns a result to inspect.
    try:
        if args.command == "ingest":
            ingest_result = _run(args.base_url, lambda c: ingest(c, directory=args.directory, on_progress=print))
            if ingest_result.errors:
                for error in ingest_result.errors:
                    print(f"  ERROR: {error}")
                sys.exit(1)

        elif args.command == "import":
            import_result = _run(
                args.base_url,
                lambda c: import_app(
                    c,
                    directory=args.directory,
                    org_unit_id=args.org_unit_id,
                    brand_id=args.brand_id,
                    name=args.name,
                    on_progress=print,
                ),
            )
            errors = [e for r in import_result.ingest_results for e in r.errors]
            if errors:
                for error in errors:
                    print(f"  ERROR: {error}")
                sys.exit(1)

        elif args.command == "org-units":
            if args.subcommand == "list":
                _print_table(_run(args.base_url, lambda c: list_org_units(c)), ["id", "name", "parent_id"])
            elif args.subcommand == "create":
                new_id = _run(args.base_url, lambda c: create_org_unit(c, name=args.name, parent_id=args.parent_id))
                print(f"Created org unit {new_id}")

        elif args.command == "brands":
            _print_table(_run(args.base_url, lambda c: list_brands(c)), ["id", "name"])
    except (CliError, ValueError) as error:
        print(f"  ERROR: {error}")
        sys.exit(1)
