"""A `skips` entry the chain no longer bears out is refused, so a declared
crossing is re-examined when the revisions under it move rather than passing
silently. Each case reds when the harness stops checking its skips.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.migrations.harness import restore_world

_ENFORCEMENT = "8b3a1162eb95"
_BELOW_THE_FLOOR = "48770eba4885"


async def test_a_skip_whose_downgrade_runs_is_refused(db_session: AsyncSession) -> None:
    with pytest.raises(AssertionError, match=_ENFORCEMENT):
        await restore_world(db_session, _ENFORCEMENT, skips=(_ENFORCEMENT,))


async def test_a_skip_the_walk_never_reaches_is_refused(db_session: AsyncSession) -> None:
    with pytest.raises(AssertionError, match=_BELOW_THE_FLOOR):
        await restore_world(db_session, _ENFORCEMENT, skips=(_BELOW_THE_FLOOR,))
