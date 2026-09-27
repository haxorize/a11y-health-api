"""Migration-body coverage for revision 8b3a1162eb95 (the #98 uniqueness
enforcement).

Proves the enforcement chain on legacy data: seed pre-#95 duplicate rollup rows,
run the shipped #97 cleanup, then the shipped enforcement upgrade — which must
succeed on the cleaned data (AC3), leave both partial unique indexes in place,
and remove the single-column owner indexes they subsume. Also proves enforcement
alone survives duplicates raced in *after* the cleanup shipped (the #97→#98
deploy window), collapsing them to the row latest selection serves. Harness
mechanics live in tests/migrations/harness.py.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.score_snapshot import (
    UQ_SCORE_SNAPSHOT_BRAND_SNAPSHOT_AT,
    UQ_SCORE_SNAPSHOT_ORG_UNIT_SNAPSHOT_AT,
)
from tests.factories import make_brand, make_org_unit, make_score_snapshot
from tests.migrations.harness import (
    DUPLICATE_CLEANUP,
    UNIQUENESS_ENFORCEMENT,
    load_migration,
    restore_pre_migration_schema,
    run_upgrade,
)

cleanup = load_migration(DUPLICATE_CLEANUP)
enforcement = load_migration(UNIQUENESS_ENFORCEMENT)

_OBSERVED_AT = datetime(2026, 3, 1, 9, 0, 0, tzinfo=UTC)

_INDEXES = (UQ_SCORE_SNAPSHOT_ORG_UNIT_SNAPSHOT_AT, UQ_SCORE_SNAPSHOT_BRAND_SNAPSHOT_AT)
_SUBSUMED_INDEXES = ("ix_score_snapshot_org_unit_id", "ix_score_snapshot_brand_id")


async def _rollup_survivors(db_session: AsyncSession) -> set[int]:
    rows = await db_session.execute(
        text("SELECT id FROM score_snapshot WHERE org_unit_id IS NOT NULL OR brand_id IS NOT NULL")
    )
    return set(rows.scalars())


@pytest.fixture(autouse=True)
async def _pre_enforcement_db(db_session: AsyncSession) -> None:
    await restore_pre_migration_schema(db_session, enforcement.revision)


async def test_enforcement_applies_cleanly_after_cleanup_on_legacy_duplicates(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)
    await make_score_snapshot(db_session, org_unit_id=org_unit.id, snapshot_at=_OBSERVED_AT)
    org_unit_winner = await make_score_snapshot(db_session, org_unit_id=org_unit.id, snapshot_at=_OBSERVED_AT)
    await make_score_snapshot(db_session, brand_id=brand.id, snapshot_at=_OBSERVED_AT)
    brand_winner = await make_score_snapshot(db_session, brand_id=brand.id, snapshot_at=_OBSERVED_AT)

    await run_upgrade(db_session, cleanup)
    # Checked between the two, because enforcement collapses duplicates on its
    # own and would hide a cleanup that deleted nothing. Reds when the
    # cleanup's upgrade is stubbed out.
    assert await _rollup_survivors(db_session) == {org_unit_winner.id, brand_winner.id}

    await run_upgrade(db_session, enforcement)

    assert await _rollup_survivors(db_session) == {org_unit_winner.id, brand_winner.id}
    indexes = set(
        (
            await db_session.execute(text("SELECT indexname FROM pg_indexes WHERE tablename = 'score_snapshot'"))
        ).scalars()
    )
    assert set(_INDEXES) <= indexes
    assert indexes.isdisjoint(_SUBSUMED_INDEXES)


async def test_enforcement_alone_collapses_duplicates_raced_in_after_cleanup(db_session: AsyncSession) -> None:
    # The #97→#98 deploy window: cleanup already ran, pre-#98 code raced a
    # duplicate in. Index creation must not fail on it.
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)
    await make_score_snapshot(db_session, org_unit_id=org_unit.id, snapshot_at=_OBSERVED_AT)
    org_unit_winner = await make_score_snapshot(db_session, org_unit_id=org_unit.id, snapshot_at=_OBSERVED_AT)
    await make_score_snapshot(db_session, brand_id=brand.id, snapshot_at=_OBSERVED_AT)
    brand_winner = await make_score_snapshot(db_session, brand_id=brand.id, snapshot_at=_OBSERVED_AT)

    await run_upgrade(db_session, enforcement)

    assert await _rollup_survivors(db_session) == {org_unit_winner.id, brand_winner.id}
