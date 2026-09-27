"""A `skips` entry the chain no longer bears out is refused, so a declared
crossing is re-examined when the revisions under it move rather than passing
silently. Each case reds when the harness stops checking its skips.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.migrations.harness import SLUG_REPAIR, UNIQUENESS_ENFORCEMENT, StaleSkipError, restore_pre_migration_schema


async def test_a_skip_whose_downgrade_runs_is_refused(db_session: AsyncSession) -> None:
    with pytest.raises(StaleSkipError) as exc_info:
        await restore_pre_migration_schema(db_session, UNIQUENESS_ENFORCEMENT, skips=(UNIQUENESS_ENFORCEMENT,))
    assert exc_info.value.stale == {UNIQUENESS_ENFORCEMENT}


async def test_a_skip_the_walk_never_reaches_is_refused(db_session: AsyncSession) -> None:
    # The slug repair lies below the enforcement revision, so this walk stops
    # before it.
    with pytest.raises(StaleSkipError) as exc_info:
        await restore_pre_migration_schema(db_session, UNIQUENESS_ENFORCEMENT, skips=(SLUG_REPAIR,))
    assert exc_info.value.stale == {SLUG_REPAIR}
