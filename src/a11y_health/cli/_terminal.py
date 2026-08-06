"""The terminal surface — argument parsing, table printing, exit codes.

Charter: everything between the operator's shell and a client operation, and
nothing else. It parses argv, calls one operation, renders what comes back, and
chooses an exit code. No decision about *what* a command means lives here; a
new command adds a subparser and a dispatch branch, and its behavior belongs in
`_scan` or `_client`.

The operations are imported by name so a dispatch test can substitute one with
`monkeypatch.setattr`.
"""

import argparse
import asyncio
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx

from a11y_health.cli._client import create_org_unit, list_brands, list_org_units
from a11y_health.cli._errors import CliError
from a11y_health.cli._operations import import_app, ingest


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
    except CliError as error:
        # Only the declared operator failures collapse to a line and an exit
        # code. Anything else is a defect and keeps its traceback.
        print(f"  ERROR: {error}")
        sys.exit(1)
    except KeyboardInterrupt:
        # Not an error either way — the operator asked to stop. 130 is the
        # shell's code for SIGINT. A Scan Run created before the interrupt is
        # left Pending and unscored, the same state a failed page upload leaves
        # behind.
        print("\n  Interrupted.")
        sys.exit(130)
