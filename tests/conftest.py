import json
import os
import pickle
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from types import MappingProxyType
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine

import a11y_health
from a11y_health.config import settings
from a11y_health.core.database import Base, SessionSource, bind_session_source
from a11y_health.main import app
from a11y_health.models import *  # noqa: F403 — ensure all models are registered
from tests import _declaration_honesty
from tests._declaration_honesty import DeclarationHonestyShim, instrument_rollup_raisers
from tests._non_test_database import allow_maintenance_engine, install_non_test_database_guard
from tests.factories import SessionFactory
from tests.import_graph import Module, package_edges

FIXTURE_DIR = Path(__file__).parent / "fixtures"

declaration_honest_app = DeclarationHonestyShim(app)
_honest_transport = ASGITransport(app=declaration_honest_app)
instrument_rollup_raisers()
# Armed at import so it covers collection-time connections too, not only ones
# opened from inside a test. The invariant it holds, and why CI's env value was
# not enough on its own, are tests/_non_test_database.py.
install_non_test_database_guard()


def pytest_configure(config: pytest.Config) -> None:
    # The session gate's hooks, registered as a plugin: imported here by name
    # behind a noqa, an import cleanup would drop the gate without a sound.
    config.pluginmanager.register(_declaration_honesty, "declaration_honesty")


@asynccontextmanager
async def _admin_connection(admin_url: str) -> AsyncIterator[AsyncConnection]:
    """A maintenance connection, in AUTOCOMMIT.

    CREATE DATABASE cannot run from inside the database being created, nor
    inside a transaction; `postgres` is the maintenance database every
    deployment has.
    """
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    allow_maintenance_engine(admin)
    try:
        async with admin.connect() as conn:
            yield conn
    finally:
        await admin.dispose()


async def _drop(conn: AsyncConnection, name: str) -> None:
    # A previous run killed mid-suite can leave a backend still attached to its
    # database: a connection whose process died without being reaped, or a
    # concurrent run on a collided pid. DROP DATABASE fails while one is open,
    # so terminate first.
    await conn.execute(
        text("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = :name"),
        {"name": name},
    )
    await conn.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))


def per_run_test_database_name() -> str:
    # Suffixed with the pid because `_per_run_test_database` drops and recreates
    # it, so two runs sharing one name would drop each other's schema — and the
    # pre-commit hook runs the suite on every commit while the developer may be
    # running `make test` in another terminal.
    return f"{make_url(settings.TEST_DATABASE_URL).database}_{os.getpid()}"


@asynccontextmanager
async def _per_run_test_database() -> AsyncIterator[str]:
    """Yields the URL of a database that exists for the block and not after.

    One seam for the whole lifecycle, so a caller never handles the admin URL
    or the bare name — the two values that, loose, let a caller aim the drop at
    something else.
    """
    template = make_url(settings.TEST_DATABASE_URL)
    name = per_run_test_database_name()
    # The identifier cannot be a bound parameter the way the datname filter in
    # _drop is. Double-quoting neutralizes every metacharacter except a quote,
    # which would escape it — so the quote is what this refuses, once, covering
    # both the CREATE below and every DROP.
    assert '"' not in name, f"TEST_DATABASE_URL names an unusable database: {name!r}"
    admin_url = template.set(database="postgres").render_as_string(hide_password=False)

    async with _admin_connection(admin_url) as conn:
        await _drop(conn, name)
        await conn.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        yield template.set(database=name).render_as_string(hide_password=False)
    finally:
        async with _admin_connection(admin_url) as conn:
            await _drop(conn, name)


@pytest.fixture(scope="session")
async def engine() -> AsyncIterator[AsyncEngine]:
    async with _per_run_test_database() as run_url:
        eng = create_async_engine(
            run_url,
            echo=settings.DEBUG,
            # Deadlock tests would otherwise idle out the 1s default before
            # detection fires. PGC_SUSET — dev and CI connect as superuser
            # (#112).
            connect_args={"server_settings": {"deadlock_timeout": "50ms"}},
        )
        async with eng.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        try:
            yield eng
        finally:
            # Before the context manager's drop: DROP DATABASE fails while a
            # backend is attached, and this pool holds them.
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


class _SharedSession(SessionSource):
    """Hands every request the test's own `db_session` and stops there: no
    commit, no rollback, so the test asserts through the session that served
    the request (ADR 0007) and its outer rollback still isolates it (ADR
    0011)."""

    def __init__(self, session: AsyncSession, engine: AsyncEngine) -> None:
        super().__init__(engine)
        self._session = session

    @asynccontextmanager
    async def request_session(self) -> AsyncIterator[AsyncSession]:
        yield self._session


@pytest.fixture
async def db_client(engine: AsyncEngine, db_session: AsyncSession) -> AsyncIterator[AsyncClient]:
    with bind_session_source(_SharedSession(db_session, engine)):
        async with AsyncClient(transport=_honest_transport, base_url="http://test") as ac:
            yield ac


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
        await truncate_every_table(engine)


async def truncate_every_table(engine: AsyncEngine, *, lock_timeout: str = "5s") -> None:
    # A transaction still open on these tables (a test that also took
    # db_session, which rolls back after this runs) would otherwise hold the
    # truncate's ACCESS EXCLUSIVE wait, and the suite, forever.
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    async with engine.begin() as conn:
        await conn.execute(text("SELECT set_config('lock_timeout', :value, true)"), {"value": lock_timeout})
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture(scope="session")
def _axe_payload_pickle() -> bytes:
    # Parsed once per run. Loading pickled bytes is the cheapest fresh deep
    # copy of the 1 MB document, cheaper than re-parsing it or `deepcopy`.
    return pickle.dumps(json.loads((FIXTURE_DIR / "humana.com-home.json").read_text()))


@pytest.fixture
def axe_payload(_axe_payload_pickle: bytes) -> dict[str, Any]:
    # A fresh copy per test, so one test's mutation never reaches the next.
    return pickle.loads(_axe_payload_pickle)


@pytest.fixture(scope="session")
def source_edges() -> Mapping[Module, frozenset[str]]:
    """`package_edges` over `src/`, walked and parsed once per run for every
    topology guard that reads the real tree; read-only, since they share it."""
    return MappingProxyType(package_edges(a11y_health))
