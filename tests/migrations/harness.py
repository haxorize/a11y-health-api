"""Harness for migration-body tests: run a shipped `upgrade()` or
`downgrade()` against the test database.

`load_migration` imports a revision module by filename (the leading digit means
it can't be imported by name). The runners bind Alembic's module-level `op`
proxy to the test's own connection via `Operations.context`, so `op.get_bind()`
resolves without standing up a full env.py run or touching the alembic_version
table. Everything runs inside the standard rolled-back `db_session`
transaction (ADR 0011).

The test engine builds the *current* schema from model metadata; a test that
needs the pre-migration world restores it with `run_downgrade`, so the baseline
comes from the shipped downgrade rather than a hand-maintained copy. A
single-step restore is faithful only while no revision after the one being
downgraded touches the schema the test exercises; once one lands, chain
`run_downgrade` calls newest-first to reach the intended baseline.
"""

import importlib.util
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession

_VERSIONS_DIR = Path(__file__).resolve().parents[2] / "migrations" / "versions"


def load_migration(filename: str) -> ModuleType:
    revision = filename.split("_", 1)[0]
    spec = importlib.util.spec_from_file_location(f"migration_{revision}", _VERSIONS_DIR / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _run_bound(db_session: AsyncSession, migration_fn: Callable[[], None]) -> None:
    def _run(sync_conn: Connection) -> None:
        with Operations.context(MigrationContext.configure(connection=sync_conn)):
            migration_fn()

    await (await db_session.connection()).run_sync(_run)


async def run_upgrade(db_session: AsyncSession, migration: ModuleType) -> None:
    await _run_bound(db_session, migration.upgrade)


async def run_downgrade(db_session: AsyncSession, migration: ModuleType) -> None:
    await _run_bound(db_session, migration.downgrade)
