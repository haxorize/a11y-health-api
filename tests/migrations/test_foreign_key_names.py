"""Every foreign key the migrations leave at the head carries the name the
models give it. Alembic's autogenerate matches foreign keys by their columns
and referent and ignores the name, so the drift job cannot see a rename that
a migration missed (ADR 0051).
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine

_FOREIGN_KEYS = text(
    "SELECT conrelid::regclass::text AS tbl, conname, pg_get_constraintdef(oid) AS definition"
    " FROM pg_constraint WHERE contype = 'f' AND connamespace = 'public'::regnamespace"
)


async def _foreign_keys(conn: AsyncConnection) -> dict[tuple[str, str], str]:
    return {(row.tbl, row.conname): row.definition for row in await conn.execute(_FOREIGN_KEYS)}


async def test_the_migrated_foreign_key_names_are_the_models(migrated_database_url: str, engine: AsyncEngine) -> None:
    migrated_engine = create_async_engine(migrated_database_url)
    try:
        async with migrated_engine.connect() as conn:
            migrated = await _foreign_keys(conn)
    finally:
        await migrated_engine.dispose()
    # `engine` builds its schema from the models' metadata.
    async with engine.connect() as conn:
        modeled = await _foreign_keys(conn)

    # An empty read on both sides would compare equal and prove nothing.
    assert migrated, "read no foreign keys from the migrated database"
    assert migrated == modeled
