"""The factories' own reading of Latest Score Snapshot, which every scoring
and rollup test asserts through. It is written out here rather than imported
from the service that defines it, so a test never checks production's latest
against itself; this file is what holds the two to one definition.
"""

from collections.abc import Awaitable, Callable
from datetime import timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.score_snapshot import ScoreSnapshot
from tests.factories import (
    DEFAULT_SNAPSHOT_AT,
    latest_app_snapshot,
    latest_brand_snapshot,
    latest_ou_snapshot,
    make_app,
    make_app_with_org_unit,
    make_score_snapshot,
)

# One row per Owner type: its reader, the snapshot column naming the owner,
# and where the arranged App keeps that owner's id.
LATEST_READERS = [
    pytest.param(latest_app_snapshot, "app_id", "id", id="app"),
    pytest.param(latest_ou_snapshot, "org_unit_id", "org_unit_id", id="org_unit"),
    pytest.param(latest_brand_snapshot, "brand_id", "brand_id", id="brand"),
]


# Reds if a reader orders by id alone: the newer observation is the lower id.
@pytest.mark.parametrize(("read_latest", "owner_column", "app_attribute"), LATEST_READERS)
async def test_the_latest_is_the_newest_observation_not_the_highest_id(
    db_session: AsyncSession,
    read_latest: Callable[[AsyncSession, int], Awaitable[ScoreSnapshot]],
    owner_column: str,
    app_attribute: str,
) -> None:
    app = await make_app_with_org_unit(db_session)
    owner_id = getattr(app, app_attribute)
    owner = {owner_column: owner_id}
    newer = await make_score_snapshot(db_session, **owner, snapshot_at=DEFAULT_SNAPSHOT_AT + timedelta(days=1))
    await make_score_snapshot(db_session, **owner, snapshot_at=DEFAULT_SNAPSHOT_AT)

    latest = await read_latest(db_session, owner_id)

    assert latest.id == newer.id


# Only an App can hold two snapshots at one observation time; the rollup
# owners' unique index refuses the second.
async def test_an_observation_time_tie_goes_to_the_highest_id(db_session: AsyncSession) -> None:
    app = await make_app_with_org_unit(db_session)
    rewritten = await make_score_snapshot(db_session, app_id=app.id)
    highest = await make_score_snapshot(db_session, app_id=app.id)
    # Moving the row to another App and back gives it a new row version and a
    # new index entry, both after the other row's. Disk order then no longer
    # matches id order, so a read without the tie-break picks the wrong one;
    # insert order alone matches it, and such a read would still pass.
    elsewhere = await make_app(db_session, slug="elsewhere", org_unit_id=app.org_unit_id)
    for owner in (elsewhere, app):
        await db_session.execute(update(ScoreSnapshot).where(ScoreSnapshot.id == rewritten.id).values(app_id=owner.id))

    latest = await latest_app_snapshot(db_session, app.id)

    assert latest.id == highest.id
