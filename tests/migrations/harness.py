"""Harness for migration-body tests: run a shipped `upgrade()` against the
test database in the schema its revision was written against.

A test declares the revision it exercises rather than inheriting whatever
baseline an earlier downgrade left (#172). The shipped downgrades run on the
test's own connection inside the rolled-back `db_session` transaction
(ADR 0011), so nothing a walk does outlives the test.

The schema is genuinely older, but tests/factories.py builds head-schema rows:
a test seeds through the factories only where no revision the walk undid
changed the tables it seeds, and through raw SQL otherwise.
"""

from collections.abc import Callable
from functools import cache
from pathlib import Path
from types import ModuleType

from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession

_REPO = Path(__file__).resolve().parents[2]


class IrreversibleRevisionError(Exception):
    def __init__(self, revision: str) -> None:
        self.revision = revision
        super().__init__(
            f"Cannot downgrade below an irreversible revision ({revision}). "
            f"Name it in skips only if it changes no schema the test exercises."
        )


class StaleSkipError(Exception):
    def __init__(self, stale: frozenset[str]) -> None:
        self.stale = stale
        super().__init__(
            f"Skips that no longer describe the chain: {sorted(stale)}. "
            f"The walk downgraded each one, or never reached it."
        )


# The revisions the migration tests name, one spelling each.
#
# The #97 legacy-duplicate cleanup. Its downgrade raises because the rows it
# deleted are gone, but it changes no schema, so a test whose schema lies below
# it may name it in `skips`.
DUPLICATE_CLEANUP = "b362121027a0"
# The #98 per-owner rollup uniqueness indexes.
UNIQUENESS_ENFORCEMENT = "8b3a1162eb95"
# The ADR-0019 slug repair. Its downgrade raises too, since the slugs it
# rewrote are not preserved.
SLUG_REPAIR = "48770eba4885"


@cache
def script_directory() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(_REPO / "alembic.ini")))


def load_migration(revision: str) -> ModuleType:
    script = script_directory().get_revision(revision)
    assert script is not None
    return script.module


async def _run_bound(db_session: AsyncSession, migration_fn: Callable[[], None]) -> None:
    def _run(sync_conn: Connection) -> None:
        with Operations.context(MigrationContext.configure(connection=sync_conn)):
            migration_fn()

    await (await db_session.connection()).run_sync(_run)


async def run_upgrade(db_session: AsyncSession, migration: ModuleType) -> None:
    await _run_bound(db_session, migration.upgrade)


async def restore_pre_migration_schema(db_session: AsyncSession, revision: str, *, skips: tuple[str, ...] = ()) -> None:
    """Runs each shipped `downgrade()` from the head down to and including
    `revision`. A revision named in `skips` may raise `NotImplementedError`,
    which declares it changes no schema the test exercises, and is left undone;
    any other that raises stops the walk with `IrreversibleRevisionError`."""
    refused: set[str] = set()
    for current in script_directory().iterate_revisions("heads", revision, inclusive=True):
        try:
            await _run_bound(db_session, current.module.downgrade)
        except NotImplementedError as exc:
            if current.revision not in skips:
                raise IrreversibleRevisionError(current.revision) from exc
            refused.add(current.revision)
    # A skip the walk downgraded, or never reached, no longer describes the
    # chain; kept, it would pass a revision nobody re-examined.
    stale = frozenset(skips) - refused
    if stale:
        raise StaleSkipError(stale)
