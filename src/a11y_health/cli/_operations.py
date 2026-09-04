"""The two onboarding operations — `ingest` and `import`.

Charter: everything that needs both sides at once. `_scan` reads directories,
validates every file at the axe boundary, and knows nothing about the API;
`_client` makes requests and knows nothing about disk. The read-then-upload
order lives here, with the failures only the combination can produce — an App
the scan names but the server doesn't have, an override that disagrees with the
document it overrides.

Holding this apart is what makes `_scan` and `_client` peers instead of a chain:
neither imports the other, and each is drivable on its own. It also means a
failure that happens before the first request can be tested without a server.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from a11y_health.cli import _client
from a11y_health.cli._errors import CliError
from a11y_health.cli._scan import (
    InvalidScanFilesError,
    LoadedScan,
    UnderivableAppNameError,
    find_date_dirs,
    load_scan,
    resolve_app_name,
)
from a11y_health.core.exceptions import InvalidAxePayloadError
from a11y_health.core.slug import derive_slug

ProgressCallback = Callable[[str], None]


def _noop(_msg: str) -> None:
    pass


class AppNotFoundError(CliError):
    def __init__(self, name: str, slug: str) -> None:
        self.name = name
        self.slug = slug
        super().__init__(
            f"App with slug {slug!r} (derived from axe JSON name {name!r}) not found. "
            "Run `a11y import <dir> --org-unit-id <id> --brand-id <id>` to onboard a new app."
        )


class NameOverrideMismatchError(CliError):
    # Takes both slugs rather than re-deriving them: the caller has just
    # computed both to discover the mismatch, and an exception that derives in
    # its own constructor is one that can raise while being raised.
    def __init__(self, *, name: str, name_slug: str, json_name: str, json_slug: str) -> None:
        self.name = name
        self.name_slug = name_slug
        self.json_name = json_name
        self.json_slug = json_slug
        super().__init__(
            f"--name {name!r} derives to slug {name_slug!r}, but the axe JSON name {json_name!r} "
            f"derives to {json_slug!r}. The override must derive to the same slug, "
            "or future imports of this directory would resolve to a different App."
        )


def _left_pending(scan_run_id: int, detail: str) -> str:
    return (
        f"Scan run {scan_run_id} left pending: {detail} — fix the problem and re-ingest, then delete run {scan_run_id}"
    )


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
    on_progress: ProgressCallback,
) -> IngestResult:
    scan_run_id = await _client.create_scan_run(client, app_id=app_id, scanned_at=scan.scanned_at)
    on_progress(f"Created scan run {scan_run_id}")

    errors: list[str] = []
    pages_uploaded = 0
    try:
        for file in scan.files:
            rejection = await _client.upload_page(client, scan_run_id=scan_run_id, payload=file.document)
            if rejection is None:
                pages_uploaded += 1
                on_progress(f"Uploaded {file.path.name}")
            else:
                errors.append(f"{file.path.name}: {rejection}")
                on_progress(f"Failed {file.path.name}: {rejection.code}")

        if errors:
            # A partial run must not be scored: completing it would snapshot a
            # score over whatever subset happened to upload. Leave it Pending
            # (unscored), so the operator can fix the inputs and re-ingest,
            # then delete it.
            on_progress(_left_pending(scan_run_id, f"{len(errors)} of {len(scan.files)} pages failed"))
        else:
            await _client.complete_scan_run(client, scan_run_id=scan_run_id)
            on_progress(f"Scan run {scan_run_id} completed: {pages_uploaded} pages uploaded")
    except CliError as exc:
        # The run exists and holds whatever uploaded before this failure — the
        # same Pending state a partial run leaves. Without this it is abandoned
        # unnamed, and the operator has no id to delete.
        on_progress(_left_pending(scan_run_id, str(exc)))
        raise

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
    on_progress: ProgressCallback = _noop,
) -> IngestResult:
    scan = load_scan(directory)
    on_progress(f"Found {len(scan.files)} JSON files in {directory}")

    name = resolve_app_name([scan])
    slug = derive_slug(name)

    app = await _client.find_app_by_slug(client, slug)
    if app is None:
        raise AppNotFoundError(name, slug)
    app_id = app["id"]
    on_progress(f"Resolved app '{slug}' (id={app_id})")

    return await _upload_scan(
        client,
        app_id=app_id,
        app_slug=slug,
        scan=scan,
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
    on_progress: ProgressCallback = _noop,
) -> ImportResult:
    date_dirs, skipped = find_date_dirs(directory)
    if skipped:
        on_progress(f"Skipping non-date entries: {', '.join(e.name for e in skipped)}")

    # Every date directory is loaded before the first request, and every
    # schema-invalid file across all of them is reported at once: an import
    # that failed on one file per run would cost one re-run per bad file.
    scans: list[LoadedScan] = []
    failures: list[tuple[Path, InvalidAxePayloadError]] = []
    for date_dir in date_dirs:
        try:
            scans.append(load_scan(date_dir))
        except InvalidScanFilesError as exc:
            failures.extend(exc.failures)
    if failures:
        raise InvalidScanFilesError(failures)
    json_name = resolve_app_name(scans)
    slug = derive_slug(json_name)

    existing = await _client.find_app_by_slug(client, slug)
    if existing is None:
        # Equivalence is only enforced when the override actually names the
        # App; on an existing App the override is ignored below, mismatched or
        # not (AC10).
        if name is not None:
            try:
                override_slug = derive_slug(name)
            except ValueError as exc:
                raise UnderivableAppNameError(name, exc) from exc
            if override_slug != slug:
                raise NameOverrideMismatchError(name=name, name_slug=override_slug, json_name=json_name, json_slug=slug)
        app_id = await _client.create_app(client, name=name or json_name, brand_id=brand_id, org_unit_id=org_unit_id)
        app_created = True
        on_progress(f"Created app '{slug}' (id={app_id})")
    else:
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
                on_progress=on_progress,
            )
        )

    return ImportResult(app_id=app_id, app_slug=slug, app_created=app_created, ingest_results=ingest_results)
