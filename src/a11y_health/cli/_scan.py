"""Scan loading and App-name resolution — the CLI's read side.

Charter: everything between a directory on the operator's disk and the facts
the client needs before it can talk to the API — directory walking, JSON
loading, and resolving the App name that identifies the target App. Nothing
here knows the API exists.

Two raw axe fields are read straight from the document rather than through the
ingest schema, because both are needed *before* any upload exists to validate:
`name` supplies the Slug that identifies the App (ADR 0019), and `endTime`
orders Scan Runs by observation time. These are client-side wire facts about
the axe document — `schemas/axe_payload.py`, the server's axe boundary, models
neither field, and the two readings share no vocabulary on purpose.
"""

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

from a11y_health.cli._errors import CliError
from a11y_health.core.slug import derive_slug


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
        # `None` when the name came from `--name` rather than from a document, which
        # is the only case where there is no file to point at.
        self.file = file
        # The derivation's own wording, not a paraphrase of it — only `derive_slug`
        # knows whether the name emptied out or ran past the slug length bound.
        super().__init__(f"{file}: {reason}" if file else str(reason))


class MalformedScanFileError(CliError):
    """One unreadable scan file. `detail` completes the sentence "<file> ..." because
    the three ways a file can be unreadable — bad JSON syntax, bytes that aren't text,
    a document that isn't an object — are one failure to the operator but three
    different things to say."""

    def __init__(self, file: Path, detail: str) -> None:
        self.file = file
        self.detail = detail
        super().__init__(f"{file} {detail}")


class UnparseableScanTimestampError(CliError):
    def __init__(self, file: Path, end_time: object, reason: ValueError | TypeError) -> None:
        self.file = file
        self.end_time = end_time
        self.reason = reason
        super().__init__(f"{file} has an unreadable 'endTime' {end_time!r}: {reason}")


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


def _is_date_dir(name: str) -> bool:
    try:
        datetime.strptime(name, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def _parse_scanned_at(files: list[Path], payloads: list[dict], directory: Path) -> datetime:
    for file, payload in zip(files, payloads, strict=True):
        if end_time := payload.get("endTime"):
            try:
                parsed = datetime.fromisoformat(end_time)
            except (ValueError, TypeError) as exc:
                raise UnparseableScanTimestampError(file, end_time, exc) from exc
            # An offset-less endTime is otherwise uncomparable against the UTC mtime
            # fallback and against sibling scans (import orders scans by scanned_at) — assume UTC.
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    mtime = directory.stat().st_mtime
    return datetime.fromtimestamp(mtime, tz=UTC)


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


@dataclass
class LoadedScan:
    directory: Path
    files: list[Path]
    payloads: list[dict]
    scanned_at: datetime


def load_scan(directory: Path) -> LoadedScan:
    if not directory.is_dir():
        raise MissingScanDirectoryError(directory)

    files = sorted(directory.glob("*.json"))
    if not files:
        raise EmptyScanDirectoryError(directory)

    payloads: list[dict] = []
    for file in files:
        try:
            payload = json.loads(file.read_text())
        except json.JSONDecodeError as exc:
            raise MalformedScanFileError(file, f"is not valid JSON: {exc}") from exc
        except UnicodeDecodeError as exc:
            # Also a ValueError, but a different thing to say: the bytes never
            # reached the JSON parser at all.
            raise MalformedScanFileError(file, f"is not valid UTF-8 text: {exc}") from exc
        if not isinstance(payload, dict):
            # Parses, but isn't an axe document. Caught here rather than at the
            # first `.get()` so the operator learns which file, not which attribute.
            raise MalformedScanFileError(
                file, f"is not an axe scan document: its top level is a JSON {type(payload).__name__}, not an object"
            )
        payloads.append(payload)

    scanned_at = _parse_scanned_at(files, payloads, directory)
    return LoadedScan(directory=directory, files=files, payloads=payloads, scanned_at=scanned_at)


def resolve_app_name(scans: list[LoadedScan]) -> str:
    # Identity is the derived slug (ADR 0019), so names that differ only in
    # presentation but derive to the same slug are the same App — not a conflict.
    # A genuine conflict is two distinct slugs. Among same-slug variants the display
    # name is cosmetic; the newest scan's variant (by observation time) wins — equal
    # scanned_at ties fall to first-seen, harmless because the pick is cosmetic.
    missing: list[Path] = []
    by_slug: dict[str, list[NameVariant]] = {}
    underivable: tuple[str, ValueError, Path] | None = None
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
            except ValueError as exc:
                # An unslugifiable name still fails loudly, but only after the
                # structured missing/conflict report below — never pre-empting it.
                underivable = underivable or (name, exc, file)
                continue
            by_slug.setdefault(slug, []).append(NameVariant(name, file))
            if newest_at is None or scan.scanned_at > newest_at:
                newest_at, newest_name = scan.scanned_at, name

    conflicts = by_slug if len(by_slug) > 1 else {}
    if missing or conflicts:
        raise NameResolutionError(missing=missing, conflicts=conflicts)
    if underivable:
        raise UnderivableAppNameError(*underivable)
    assert newest_name is not None  # exactly one slug ⇒ at least one present name
    return newest_name
