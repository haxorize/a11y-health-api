"""Migration-body coverage for revision 8fe96135b4ba (the ADR-0026 single-root
index).

What's exercised is the guarded rollout: against data that already violates the
invariant, the migration must abort with the offending ids and remediation
guidance — never a raw unique-violation error, and never an implicit rewrite of
the org structure.

The test engine creates `uq_org_unit_single_root` from model metadata, so each
test first restores the pre-migration schema (inside the rolled-back
transaction, ADR 0011), skipping the #97 duplicate cleanup on the way. Harness
mechanics live in tests/migrations/harness.py.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_org_unit
from tests.migrations.harness import DUPLICATE_CLEANUP, load_migration, restore_pre_migration_schema, run_upgrade

migration = load_migration("8fe96135b4ba")


@pytest.fixture(autouse=True)
async def _pre_index_db(db_session: AsyncSession) -> None:
    await restore_pre_migration_schema(db_session, migration.revision, skips=(DUPLICATE_CLEANUP,))


async def test_migration_aborts_naming_offenders_when_multiple_roots_exist(db_session: AsyncSession) -> None:
    root_a = await make_org_unit(db_session, name="Humana")
    root_b = await make_org_unit(db_session, name="Stray Root")

    with pytest.raises(RuntimeError, match=rf"(?s)ids \[{root_a.id}, {root_b.id}\].*[Rr]eparent"):
        await run_upgrade(db_session, migration)


async def test_migration_creates_index_when_single_root(db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    await make_org_unit(db_session, name="CenterWell", parent_id=root.id)

    await run_upgrade(db_session, migration)

    indexes = (
        await db_session.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'org_unit'"))
    ).scalars()
    assert "uq_org_unit_single_root" in set(indexes)
