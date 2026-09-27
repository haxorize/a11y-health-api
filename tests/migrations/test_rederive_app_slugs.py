"""Migration-body coverage for revision 48770eba4885 (the ADR-0019 slug repair).

`rederive_slugs` — the pure collision/empty guard — is covered in
tests/core/test_slug.py. What's exercised here is the migration's *two-phase
placeholder swap*: parking changing rows on `revision:id` before assigning
finals, so `uq_app_slug` never sees a transient collision. That logic only bites
against real colliding rows in a real database, which needs a harness that runs
the shipped `upgrade()` — not a reimplementation of it. Harness mechanics live
in tests/migrations/harness.py.

The walk to this revision's pre-migration schema skips the #97 duplicate
cleanup and this repair itself: both downgrades raise, and both rewrite rows
without changing the schema.
"""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import make_app, make_brand, make_org_unit
from tests.migrations.harness import (
    DUPLICATE_CLEANUP,
    SLUG_REPAIR,
    load_migration,
    restore_pre_migration_schema,
    run_upgrade,
)

migration = load_migration(SLUG_REPAIR)


@pytest.fixture(autouse=True)
async def _pre_repair_db(db_session: AsyncSession) -> None:
    await restore_pre_migration_schema(db_session, migration.revision, skips=(DUPLICATE_CLEANUP, migration.revision))


async def test_migration_reslugs_transiently_colliding_rows(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)

    # Two legacy rows whose correct slugs are swapped: each derives to the slug
    # the other currently holds, so a single-pass update trips uq_app_slug
    # mid-flight. Only the two-phase parking survives this.
    swap_a = await make_app(db_session, name="foo", slug="bar", org_unit_id=org_unit.id, brand_id=brand.id)
    swap_b = await make_app(db_session, name="bar", slug="foo", org_unit_id=org_unit.id, brand_id=brand.id)
    # Already in derived form — must be left untouched, never parked.
    stable = await make_app(db_session, name="baz", slug="baz", org_unit_id=org_unit.id, brand_id=brand.id)

    await run_upgrade(db_session, migration)

    rows = (await db_session.execute(text("SELECT id, name, slug FROM app"))).all()
    by_id = {r.id: (r.name, r.slug) for r in rows}
    assert by_id[swap_a.id] == ("foo", "foo")
    assert by_id[swap_b.id] == ("bar", "bar")
    assert by_id[stable.id] == ("baz", "baz")


async def test_migration_no_op_when_all_slugs_already_derived(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)
    app = await make_app(db_session, name="foo", slug="foo", org_unit_id=org_unit.id, brand_id=brand.id)
    locate = text("SELECT ctid FROM app WHERE id = :id")
    before = (await db_session.execute(locate, {"id": app.id})).scalar_one()

    await run_upgrade(db_session, migration)

    # An UPDATE writes a new row version at a new ctid even when it rewrites a
    # value to itself, so an unmoved ctid is the proof that nothing wrote the
    # row. The values alone cannot say it: a rewrite of every slug to its own
    # derived form leaves them identical. Reds when `changing` takes every row.
    after = (await db_session.execute(locate, {"id": app.id})).scalar_one()
    assert after == before
