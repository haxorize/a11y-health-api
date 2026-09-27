"""Harness for migration-body tests: run a shipped `upgrade()` against the test
database in the world of the revision it belongs to.

`load_migration` takes a revision id and returns the module from Alembic's own
revision index, the same object `restore_world` walks, so a test names a
revision one way and each revision is loaded once. The runners bind Alembic's
module-level `op` proxy to the test's own connection via `Operations.context`,
so `op.get_bind()` resolves without standing up a full env.py run or touching
the alembic_version table. Everything runs inside the standard rolled-back
`db_session` transaction (ADR 0011).

The test engine builds the *current* schema from model metadata. A test states
the revision it exercises and `restore_world` walks the recorded parents from
the head, running each shipped `downgrade()` newest first down to and including
that revision, so the baseline comes from the chain rather than from whatever a
single-step downgrade happened to leave. A revision whose downgrade raises
`NotImplementedError` stops the walk with `IrreversibleRevisionError`, the same
revision the Makefile's `DOWNGRADE_FLOOR` names. A test below it lists that
revision in `skips`, declaring it changes no schema the test exercises; the
walk then passes it undone and carries on.
"""

import asyncio
import os
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
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
            f"revision {revision} cannot be downgraded, so the walk cannot reach a world below it. "
            f"Name it in skips only if it changes no schema the test exercises."
        )


# The #97 legacy-duplicate cleanup, the downgrade floor. Its downgrade raises
# because the rows it deleted are gone, but it changes no schema, so a test
# whose world lies below it may name it in `skips`.
DUPLICATE_CLEANUP = "b362121027a0"


@cache
def script_directory() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(_REPO / "alembic.ini")))


def downgrade_floor() -> str:
    # Read from the Makefile rather than restated here: a copy in the suite
    # would be the drift this guard exists to catch, one layer further in.
    makefile = (_REPO / "Makefile").read_text()
    match = re.search(r"^DOWNGRADE_FLOOR := (\w+)$", makefile, re.MULTILINE)
    assert match is not None, "Makefile no longer defines DOWNGRADE_FLOOR as a bare assignment"
    return match.group(1)


# In a child process because migrations/env.py reads DATABASE_URL at import and
# calls asyncio.run, which the suite's running loop forbids. One child for all
# three commands: each extra interpreter costs its imports again, per commit.
_ROUNDTRIP = """
import sys
from alembic import command
from alembic.config import Config

config = Config("alembic.ini")
command.upgrade(config, "head")
command.downgrade(config, sys.argv[1])
command.upgrade(config, "head")
"""


@dataclass(frozen=True)
class Roundtrip:
    database_url: str
    returncode: int | None
    stderr: str


async def run_roundtrip(database_url: str) -> Roundtrip:
    """Leaves the database at the head, reached back up from the floor, which
    is the migrated schema every other reader of it compares against."""
    child = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        _ROUNDTRIP,
        downgrade_floor(),
        cwd=_REPO,
        env={**os.environ, "DATABASE_URL": database_url},
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await child.communicate()
    return Roundtrip(database_url, child.returncode, stderr.decode())


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


async def restore_world(db_session: AsyncSession, revision: str, *, skips: tuple[str, ...] = ()) -> None:
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
    stale = set(skips) - refused
    assert not stale, f"skips name {sorted(stale)}, which the walk downgraded or never reached"
