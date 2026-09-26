from collections.abc import AsyncGenerator
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession

from a11y_health.core.database import SessionSource, bind_session_source, get_db, session_source
from a11y_health.models import Brand
from tests.factories import SessionFactory, make_brand

# `get_db` drives real commits here, so these take `committed_session_factory`
# for its truncate and read the outcome back on a connection of its own.


async def test_get_db_commits_a_successful_request_on_the_bound_source(
    engine: AsyncEngine, committed_session_factory: SessionFactory
) -> None:
    with bind_session_source(SessionSource(engine)):
        requests = get_db()
        brand = await make_brand(await anext(requests))
        with pytest.raises(StopAsyncIteration):
            await anext(requests)

    async with committed_session_factory() as other:
        assert await other.get(Brand, brand.id) is not None


async def test_get_db_rolls_back_a_failed_request_on_the_bound_source(
    engine: AsyncEngine, committed_session_factory: SessionFactory
) -> None:
    with bind_session_source(SessionSource(engine)):
        requests = cast(AsyncGenerator[AsyncSession], get_db())
        brand = await make_brand(await anext(requests))
        with pytest.raises(RuntimeError, match="boom"):
            await requests.athrow(RuntimeError("boom"))

    async with committed_session_factory() as other:
        assert await other.get(Brand, brand.id) is None


def test_binding_a_session_source_restores_the_previous_one_on_exit(engine: AsyncEngine) -> None:
    before = session_source()
    bound = SessionSource(engine)

    with bind_session_source(bound):
        assert session_source() is bound

    assert session_source() is before
