"""`committed_session_factory`'s teardown truncate, against a transaction left
open on the same engine: the shape a test taking both it and `db_session`
produces, since `db_session` rolls back only after the truncate has run.
Without a lock timeout the truncate waits on that transaction forever and the
suite hangs with no failure to read; with one it fails naming the timeout.
"""

import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from a11y_health.models.org_unit import OrgUnit
from tests.conftest import truncate_every_table


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
