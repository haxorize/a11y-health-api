"""`committed_session_factory`'s teardown truncate, against a transaction left
open on the same engine: the shape a test taking both it and `db_session`
produces, since `db_session` rolls back only after the truncate has run.
Without a lock timeout the truncate waits on that transaction forever and the
suite hangs with no failure to read; with one the run stops naming the timeout.
"""

import asyncio
import time

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from a11y_health.models.org_unit import OrgUnit
from tests.conftest import close_and_truncate, truncate_every_table


async def test_the_truncate_fails_on_a_lock_timeout_rather_than_waiting_on_an_open_transaction(
    engine: AsyncEngine,
) -> None:
    async with engine.connect() as open_transaction:
        await open_transaction.execute(select(OrgUnit.id).limit(1))

        # The outer bound stands in for the hang: reaching it is the red.
        with pytest.raises(DBAPIError, match="lock timeout"):
            async with asyncio.timeout(5):
                await truncate_every_table(engine, lock_timeout="100ms")

        await open_transaction.rollback()


# The fixture's own teardown at its default timeout: the run stops rather than
# leaving committed rows for every later test to fail on.
async def test_the_fixture_teardown_stops_the_run_after_its_default_lock_timeout(engine: AsyncEngine) -> None:
    async with engine.connect() as open_transaction:
        await open_transaction.execute(select(OrgUnit.id).limit(1))
        started = time.monotonic()

        with pytest.raises(pytest.exit.Exception, match="lock_timeout"):
            async with asyncio.timeout(15):
                await close_and_truncate([], engine)

        assert 4.5 < time.monotonic() - started < 10
        await open_transaction.rollback()
