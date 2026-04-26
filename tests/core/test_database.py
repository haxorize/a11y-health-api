from collections.abc import AsyncGenerator
from typing import cast
from unittest.mock import AsyncMock

import pytest
from pytest_mock import MockerFixture
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core import database as db_module


def _patch_session(mocker: MockerFixture) -> AsyncMock:
    session = mocker.AsyncMock()
    cm = mocker.AsyncMock()
    cm.__aenter__.return_value = session
    mocker.patch.object(db_module, "async_session", return_value=cm)
    return session


async def test_get_db_commits_on_success(mocker: MockerFixture) -> None:
    session = _patch_session(mocker)

    gen = db_module.get_db()
    yielded = await anext(gen)
    assert yielded is session
    with pytest.raises(StopAsyncIteration):
        await anext(gen)

    session.commit.assert_awaited_once()
    session.rollback.assert_not_called()


async def test_get_db_rolls_back_on_exception(mocker: MockerFixture) -> None:
    session = _patch_session(mocker)

    gen = cast(AsyncGenerator[AsyncSession], db_module.get_db())
    await anext(gen)

    with pytest.raises(RuntimeError, match="boom"):
        await gen.athrow(RuntimeError("boom"))

    session.rollback.assert_awaited_once()
    session.commit.assert_not_called()
