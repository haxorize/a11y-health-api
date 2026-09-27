"""Every check constraint the migrations leave at the head is the one the models
declare. Alembic's autogenerate compares no check-constraint text, so the drift
job cannot see a model's constraint, or a bound it reads from `core/slug`, that
moved without a migration behind it.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

from tests.migrations.harness import Roundtrip

_CHECKS = text(
    "SELECT conrelid::regclass::text AS tbl, conname, pg_get_constraintdef(oid) AS definition"
    " FROM pg_constraint WHERE contype = 'c' AND connamespace = 'public'::regnamespace"
)


async def _checks(conn: AsyncConnection) -> dict[tuple[str, str], str]:
    return {(row.tbl, row.conname): row.definition for row in await conn.execute(_CHECKS)}


async def test_the_migrated_check_constraints_are_the_models(roundtrip: Roundtrip, engine: AsyncEngine) -> None:
    assert roundtrip.returncode == 0, "the roundtrip failed; test_the_revisions_above_the_floor_reverse shows why"

    migrated_engine = create_async_engine(roundtrip.database_url)
    try:
        async with migrated_engine.connect() as conn:
            migrated = await _checks(conn)
    finally:
        await migrated_engine.dispose()
    # `engine` builds its schema from the models' metadata.
    async with engine.connect() as conn:
        modeled = await _checks(conn)

    # An empty read on both sides would compare equal and prove nothing.
    assert migrated, "read no check constraints from the migrated database"
    assert migrated == modeled
