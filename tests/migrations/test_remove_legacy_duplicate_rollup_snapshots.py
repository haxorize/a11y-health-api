"""Migration-body coverage for revision b362121027a0 (the #97 legacy-duplicate
cleanup).

Exercises the shipped `upgrade()` against real legacy rows: per rollup owner and
observation time, all but the row Latest Score Snapshot selection keeps (max id
at that `snapshot_at`) must be deleted, and everything else must pass through
untouched. Harness mechanics live in tests/migrations/harness.py.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import (
    app_snapshots,
    brand_snapshots,
    make_app_with_org_unit,
    make_org_unit,
    make_score_snapshot,
    ou_snapshots,
)
from tests.migrations.harness import load_migration, run_downgrade, run_upgrade

migration = load_migration("b362121027a0_remove_legacy_duplicate_rollup_snapshots.py")
enforcement = load_migration("8b3a1162eb95_add_per_owner_rollup_snapshot_uniqueness_indexes.py")

_OBSERVED_AT = datetime(2026, 3, 1, 9, 0, 0, tzinfo=UTC)


# The cleanup ran before #98's uniqueness enforcement existed; step the schema
# back through the shipped #98 downgrade or the legacy duplicates seeded here
# would violate the new indexes.
@pytest.fixture(autouse=True)
async def _pre_enforcement_db(db_session: AsyncSession) -> None:
    await run_downgrade(db_session, enforcement)


async def test_identical_org_unit_duplicates_collapse_to_max_id_row(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    await make_score_snapshot(db_session, org_unit_id=org_unit.id, snapshot_at=_OBSERVED_AT)
    survivor = await make_score_snapshot(db_session, org_unit_id=org_unit.id, snapshot_at=_OBSERVED_AT)

    await run_upgrade(db_session, migration)

    remaining = await ou_snapshots(db_session, org_unit.id)
    assert [s.id for s in remaining] == [survivor.id]


async def test_contradictory_rows_keep_the_values_latest_selection_serves(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    await make_score_snapshot(db_session, org_unit_id=org_unit.id, snapshot_at=_OBSERVED_AT, score=0.4)
    survivor = await make_score_snapshot(db_session, org_unit_id=org_unit.id, snapshot_at=_OBSERVED_AT, score=0.9)

    await run_upgrade(db_session, migration)

    remaining = await ou_snapshots(db_session, org_unit.id)
    assert [(s.id, s.score) for s in remaining] == [(survivor.id, 0.9)]


async def test_brand_duplicates_collapse_without_cross_owner_collapse(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    # Owner ids come from separate per-table sequences and can hold equal
    # values; force the collision so a coalesced partition would misgroup.
    await db_session.execute(
        text("INSERT INTO brand (id, name) OVERRIDING SYSTEM VALUE VALUES (:id, :name)"),
        {"id": org_unit.id, "name": "Colliding Brand"},
    )
    brand_id = org_unit.id

    await make_score_snapshot(db_session, brand_id=brand_id, snapshot_at=_OBSERVED_AT)
    brand_survivor = await make_score_snapshot(db_session, brand_id=brand_id, snapshot_at=_OBSERVED_AT)
    ou_row = await make_score_snapshot(db_session, org_unit_id=org_unit.id, snapshot_at=_OBSERVED_AT)

    await run_upgrade(db_session, migration)

    assert [s.id for s in await brand_snapshots(db_session, brand_id)] == [brand_survivor.id]
    assert [s.id for s in await ou_snapshots(db_session, org_unit.id)] == [ou_row.id]


async def test_distinct_observation_times_all_survive(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    history = [
        await make_score_snapshot(
            db_session, org_unit_id=org_unit.id, snapshot_at=datetime(2026, 3, day, 9, 0, 0, tzinfo=UTC)
        )
        for day in (1, 2, 3)
    ]

    await run_upgrade(db_session, migration)

    remaining = await ou_snapshots(db_session, org_unit.id)
    assert [s.id for s in remaining] == [s.id for s in history]


async def test_app_owned_rows_survive_even_when_duplicated(db_session: AsyncSession) -> None:
    app = await make_app_with_org_unit(db_session)
    kept = [
        await make_score_snapshot(db_session, app_id=app.id, snapshot_at=_OBSERVED_AT),
        await make_score_snapshot(db_session, app_id=app.id, snapshot_at=_OBSERVED_AT),
    ]

    await run_upgrade(db_session, migration)

    remaining = await app_snapshots(db_session, app.id)
    assert [s.id for s in remaining] == [s.id for s in kept]
