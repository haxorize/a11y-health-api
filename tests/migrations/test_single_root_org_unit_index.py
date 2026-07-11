"""Migration-body coverage for revision 8fe96135b4ba (the ADR-0026 single-root index).

What's exercised is the guarded rollout: against data that already violates the
invariant, the migration must abort with the offending ids and remediation
guidance — never a raw unique-violation error, and never an implicit rewrite of
the org structure.

The test engine creates `uq_org_unit_single_root` from model metadata, so each
test first drops it (inside the rolled-back transaction, ADR 0011) to simulate
a pre-migration database. Harness mechanics follow test_rederive_app_slugs.py.
"""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_org_unit

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[2] / "migrations" / "versions" / "8fe96135b4ba_add_single_root_org_unit_index.py"
)
_spec = importlib.util.spec_from_file_location("migration_8fe96135b4ba", _MIGRATION_PATH)
assert _spec is not None and _spec.loader is not None
migration = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(migration)


def _run_upgrade(sync_conn: Connection) -> None:
    with Operations.context(MigrationContext.configure(connection=sync_conn)):
        migration.upgrade()


async def _drop_index_to_simulate_pre_migration_db(db_session: AsyncSession) -> None:
    await db_session.execute(text("DROP INDEX uq_org_unit_single_root"))


async def test_migration_aborts_naming_offenders_when_multiple_roots_exist(db_session: AsyncSession) -> None:
    await _drop_index_to_simulate_pre_migration_db(db_session)
    root_a = await make_org_unit(db_session, name="Humana")
    root_b = await make_org_unit(db_session, name="Stray Root")

    with pytest.raises(RuntimeError, match=rf"(?s)ids \[{root_a.id}, {root_b.id}\].*[Rr]eparent"):
        await (await db_session.connection()).run_sync(_run_upgrade)


async def test_migration_creates_index_when_single_root(db_session: AsyncSession) -> None:
    await _drop_index_to_simulate_pre_migration_db(db_session)
    root = await make_org_unit(db_session, name="Humana")
    await make_org_unit(db_session, name="CenterWell", parent_id=root.id)

    await (await db_session.connection()).run_sync(_run_upgrade)

    indexes = (
        await db_session.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'org_unit'"))
    ).scalars()
    assert "uq_org_unit_single_root" in set(indexes)
