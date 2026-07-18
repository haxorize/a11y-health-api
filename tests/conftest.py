import json
from collections.abc import AsyncIterator
from contextlib import suppress
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from a11y_health.config import settings
from a11y_health.core.database import Base, get_db
from a11y_health.main import app
from a11y_health.models import *  # noqa: F403 — ensure all models are registered
from tests._declaration_honesty import DeclarationHonestyShim, instrument_rollup_raisers
from tests.factories import SessionFactory

FIXTURE_DIR = Path(__file__).parent / "fixtures"

_honest_transport = ASGITransport(app=DeclarationHonestyShim(app))
instrument_rollup_raisers()


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(
        settings.TEST_DATABASE_URL,
        echo=settings.DEBUG,
        # Deadlock tests would otherwise idle out the 1s default before
        # detection fires. PGC_SUSET — dev and CI connect as superuser (#112).
        connect_args={"server_settings": {"deadlock_timeout": "50ms"}},
    )
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TYPE IF EXISTS brand"))
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=_honest_transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
async def db_session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with engine.connect() as conn:
        txn = await conn.begin()
        session = AsyncSession(bind=conn, expire_on_commit=False, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            await txn.rollback()
            await session.close()


@pytest.fixture
async def db_client(db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    async def override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        async with AsyncClient(transport=_honest_transport, base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


@pytest.fixture
async def committed_session_factory(engine: AsyncEngine) -> AsyncIterator[SessionFactory]:
    """Real-commit sessions on separate connections — one session's writes
    must be visible to another, so the rollback isolation of `db_session`
    (ADR 0011) cannot apply. Teardown truncates every table instead."""
    sessions: list[AsyncSession] = []

    def factory() -> AsyncSession:
        session = AsyncSession(bind=engine, expire_on_commit=False)
        sessions.append(session)
        return session

    try:
        yield factory
    finally:
        # One broken session (e.g. a connection killed as a deadlock victim)
        # must not skip the remaining closes or the truncate below.
        for session in sessions:
            with suppress(Exception):
                await session.close()
        tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
        async with engine.begin() as conn:
            await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def axe_payload() -> dict[str, Any]:
    return json.loads((FIXTURE_DIR / "humana.com-home.json").read_text())
