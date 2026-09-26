"""Scan loading and App-name resolution — the CLI's read side.

This module owns everything between a directory on the operator's disk and the
facts the client needs before it can talk to the API — directory walking, JSON
loading, the axe boundary crossing for every file, and resolving the App
identity the Scan Directories name. Nothing here knows the API exists.

Every file crosses the axe boundary here, through the same `parse_axe_payload`
the server uses, so `name` (the Slug that identifies the App, ADR 0019) and
`endTime` (observation time, which orders Scan Runs) come off the typed model
rather than raw key reads — and a file the server would reject fails at load,
before any Scan Run exists to be left pending. The decoded document is kept
beside the typed model and is what gets uploaded, unmodeled fields and all, so
the stored Raw JSON is the document as decoded, never the model's own dump.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NamedTuple

from a11y_health.cli._errors import CliError
from a11y_health.core.exceptions import InvalidAxePayloadError
from a11y_health.core.slug import derive_slug
from a11y_health.schemas.axe_payload import AxePayload, parse_axe_payload


class MissingScanDirectoryError(CliError):
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        super().__init__(f"Directory does not exist: {directory}")


class EmptyScanDirectoryError(CliError):
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        super().__init__(f"No JSON files found in {directory}")


class UnderivableAppNameError(CliError):
    def __init__(self, name: str, reason: ValueError, file: Path | None = None) -> None:
        self.name = name
        self.reason = reason
        # `None` when the name came from `--name` rather than from a document,
        # which is the only case where there is no file to point at.
        self.file = file
        # The derivation's own wording, not a paraphrase of it — only
        # `derive_slug` knows whether the name emptied out or ran past the slug
        # length bound.
        super().__init__(f"{file}: {reason}" if file else str(reason))


class MalformedScanFileError(CliError):
    """One unreadable scan file. `detail` completes the sentence "<file> ..."
    because the two ways a file can be unreadable — bad JSON syntax, bytes that
    aren't text — are one failure to the operator but two different things to
    say. A file that reads but fails the axe boundary is
    `InvalidScanFilesError`."""

    def __init__(self, file: Path, detail: str) -> None:
        self.file = file
        self.detail = detail
        super().__init__(f"{file} {detail}")


class InvalidScanFilesError(CliError):
    """Every file that parsed as JSON but fails the axe boundary, reported
    together so one re-run fixes all of them (the same posture as
    `NameResolutionError`); a file that doesn't read at all is
    `MalformedScanFileError`. There is deliberately no flag to bypass or skip
    this check: the CLI runs the schema the server runs, so a file it refuses
    is one the same version of the server refuses. The server at `--base-url`
    can be a different version, older or newer; then the fix is matching the
    CLI to it, not a side door around the check."""

    def __init__(self, failures: list[tuple[Path, InvalidAxePayloadError]]) -> None:
        self.failures = failures
        # `reason.reason` is the bare `field: problem`; the exception's own
        # str prefixes it with "Invalid axe payload", which this sentence
        # already says.
        detail = "; ".join(f"{file}: {reason.reason}" for file, reason in failures)
        if len(failures) == 1:
            message = (
                f"1 scan file failed axe schema validation: {detail}. "
                "Fix the file; if this server accepts it as-is, "
                "the CLI and server are different versions: reinstall a11y-health at the server's version."
            )
        else:
            message = (
                f"{len(failures)} scan files failed axe schema validation: {detail}. "
                "Fix the files; if this server accepts them as-is, "
                "the CLI and server are different versions: reinstall a11y-health at the server's version."
            )
        super().__init__(message)


class NoDateDirsError(CliError):
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        super().__init__(
            f"No YYYY-MM-DD subdirectories found in {directory}. "
            "Run `a11y ingest <dir>` to upload a single scan to an existing app."
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
        # slug -> the name variants that derived to it — keyed on slug because
        # the slug is the unit of collision; same-slug variants never reach
        # here.
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


def _is_date_dir(name: str) -> bool:
    try:
        datetime.strptime(name, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _resolve_scanned_at(files: list[LoadedFile], directory: Path) -> datetime:
    end_time = next((f.payload.end_time for f in files if f.payload.end_time is not None), None)
    return end_time if end_time is not None else datetime.fromtimestamp(directory.stat().st_mtime, tz=UTC)


def find_date_dirs(directory: Path) -> tuple[list[Path], list[Path]]:
    """The YYYY-MM-DD subdirectories of `directory` and everything else in it.

    Raises `NoDateDirsError` when there are none — `import` has nothing to do
    with a directory that holds no dated scans — and `MissingScanDirectoryError`
    when `directory` isn't one, which `load_scan` raises for the same input.
    """
    if not directory.is_dir():
        raise MissingScanDirectoryError(directory)

    date_dirs: list[Path] = []
    skipped: list[Path] = []
    for entry in sorted(directory.iterdir()):
        if entry.is_dir() and _is_date_dir(entry.name):
            date_dirs.append(entry)
        else:
            skipped.append(entry)
    if not date_dirs:
        raise NoDateDirsError(directory)
    return date_dirs, skipped


class LoadedFile(NamedTuple):
    path: Path
    # The decoded JSON and its typed view travel together: the document is
    # what gets uploaded and stored as Raw JSON, the payload is what the CLI
    # reads. Keeping them in one record is what makes them impossible to
    # misalign.
    document: dict[str, Any]
    payload: AxePayload


@dataclass
class LoadedScan:
    directory: Path
    files: list[LoadedFile]
    scanned_at: datetime


def load_scan(directory: Path) -> LoadedScan:
    if not directory.is_dir():
        raise MissingScanDirectoryError(directory)

    paths = sorted(directory.glob("*.json"))
    if not paths:
        raise EmptyScanDirectoryError(directory)

    files: list[LoadedFile] = []
    failures: list[tuple[Path, InvalidAxePayloadError]] = []
    for path in paths:
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise MalformedScanFileError(path, f"is not valid JSON: {exc}") from exc
        except UnicodeDecodeError as exc:
            # Also a ValueError, but a different thing to say: the bytes never
            # reached the JSON parser at all.
            raise MalformedScanFileError(path, f"is not valid UTF-8 text: {exc}") from exc
        try:
            files.append(LoadedFile(path, document, parse_axe_payload(document)))
        except InvalidAxePayloadError as exc:
            failures.append((path, exc))
    if failures:
        raise InvalidScanFilesError(failures)

    return LoadedScan(directory=directory, files=files, scanned_at=_resolve_scanned_at(files, directory))


@dataclass(frozen=True)
class AppIdentity:
    """Identity is the Slug; the name is only presentation (ADR 0019)."""

    name: str
    slug: str

    def overridden_by(self, name: str) -> AppIdentity:
        """This identity under `--name`, refused unless the override derives to
        the same Slug."""
        try:
            slug = derive_slug(name)
        except ValueError as exc:
            raise UnderivableAppNameError(name, exc) from exc
        if slug != self.slug:
            raise NameOverrideMismatchError(name=name, name_slug=slug, json_name=self.name, json_slug=self.slug)
        return AppIdentity(name, slug)


def resolve_app_identity(scans: list[LoadedScan]) -> AppIdentity:
    # Identity is the derived slug (ADR 0019), so names that differ only in
    # presentation but derive to the same slug are the same App — not a
    # conflict. A genuine conflict is two distinct slugs. Among same-slug
    # variants the display name is cosmetic; the newest scan's variant (by
    # observation time) wins — equal scanned_at ties fall to first-seen,
    # harmless because the pick is cosmetic.
    missing: list[Path] = []
    by_slug: dict[str, list[NameVariant]] = {}
    underivable: UnderivableAppNameError | None = None
    newest_name: str | None = None
    newest_at: datetime | None = None
    for scan in scans:
        for file in scan.files:
            name = file.payload.name
            if not name:
                missing.append(file.path)
                continue
            try:
                slug = derive_slug(name)
            except ValueError as exc:
                # An unslugifiable name still fails loudly, but only after the
                # structured missing/conflict report below — never pre-empting
                # it.
                underivable = underivable or UnderivableAppNameError(name, exc, file.path)
                continue
            by_slug.setdefault(slug, []).append(NameVariant(name, file.path))
            if newest_at is None or scan.scanned_at > newest_at:
                newest_at, newest_name = scan.scanned_at, name

    conflicts = by_slug if len(by_slug) > 1 else {}
    if missing or conflicts:
        raise NameResolutionError(missing=missing, conflicts=conflicts)
    if underivable:
        raise underivable
    assert newest_name is not None  # exactly one slug ⇒ at least one present name
    (slug,) = by_slug
    return AppIdentity(newest_name, slug)
