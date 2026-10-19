"""Every foreign key column the migrations leave at the head leads some index,
so a CASCADE or RESTRICT check from the parent never scans the child. Postgres
does not index a foreign key itself, and the drift job cannot see an index
dropped or reordered in both the models and a migration.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

_UNINDEXED_FOREIGN_KEYS = text(
    "SELECT c.conname FROM pg_constraint c"
    " WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace"
    " AND NOT EXISTS (SELECT 1 FROM pg_index i"
    " WHERE i.indrelid = c.conrelid AND i.indkey[0] = c.conkey[1])"
)
_FOREIGN_KEY_COUNT = text("SELECT count(*) FROM pg_constraint WHERE contype = 'f'")


async def test_every_foreign_key_column_leads_an_index(migrated_database_url: str) -> None:
    engine = create_async_engine(migrated_database_url)
    try:
        async with engine.connect() as conn:
            unindexed = (await conn.execute(_UNINDEXED_FOREIGN_KEYS)).scalars().all()
            # No foreign keys at all would leave nothing unindexed.
            assert await conn.scalar(_FOREIGN_KEY_COUNT)
    finally:
        await engine.dispose()

    assert not unindexed
