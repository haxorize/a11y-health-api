"""The non-test-database guard's own suite — the rule, and that it is armed.

The guard is the kind that passes by never firing, so a broken one looks
exactly like a clean suite. These tests drive it directly.
"""

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from a11y_health.config import settings
from tests._non_test_database import (
    _refuse_on_connect,
    allow_maintenance_engine,
    forbidden_database,
    install_non_test_database_guard,
    refuse_non_test_database,
)
from tests.conftest import per_run_test_database_name


def test_the_forbidden_name_is_the_one_the_setting_carries() -> None:
    assert forbidden_database() == make_url(settings.DATABASE_URL).database


def test_the_non_test_database_is_refused() -> None:
    with pytest.raises(RuntimeError, match="non-test database"):
        refuse_non_test_database(forbidden_database())


def test_the_per_run_test_database_is_allowed() -> None:
    # The name the engine fixture connects to, taken from conftest rather than
    # rebuilt here. A prefix test over the forbidden name would refuse it.
    refuse_non_test_database(per_run_test_database_name())


def test_the_maintenance_database_is_allowed() -> None:
    # CREATE DATABASE runs through `postgres`; refusing it would leave the
    # suite unable to build its own database at all.
    refuse_non_test_database("postgres")


def test_a_name_that_merely_starts_with_the_forbidden_one_is_allowed() -> None:
    refuse_non_test_database(f"{forbidden_database()}_test_1")


def test_an_absent_database_name_is_allowed() -> None:
    refuse_non_test_database(None)


def test_a_database_url_naming_no_database_refuses_every_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    # The driver would fall back to PGDATABASE or the user's name, which could
    # be the real database, so an empty forbidden name fails closed.
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+asyncpg://localhost:5432")
    with pytest.raises(RuntimeError, match="names no database"):
        refuse_non_test_database(per_run_test_database_name())


def test_the_guard_is_armed_on_the_engine_class() -> None:
    # conftest installs it at import. Asserting on the registration rather than
    # on a connection attempt, because the forbidden database exists on a
    # developer's machine and not in CI, so only this half is portable.
    assert event.contains(Engine, "do_connect", _refuse_on_connect)


def test_arming_twice_registers_one_listener() -> None:
    # Counted on a fresh engine's dispatch, because `event.contains` is true of
    # one registration and of two alike. The engine is never connected. The
    # dispatch attributes are generated at runtime, so ty cannot see them.
    install_non_test_database_guard()
    install_non_test_database_guard()
    dispatch = create_engine("sqlite://").dialect.dispatch.do_connect  # ty: ignore[unresolved-attribute]
    assert sum(1 for listener in dispatch if listener is _refuse_on_connect) == 1


async def test_a_connection_to_the_non_test_database_is_refused_before_it_opens() -> None:
    # End to end through SQLAlchemy, and it proves the *pre*-connect half: the
    # URL below names a host that does not resolve, so any listener firing
    # after the driver ran would surface a connection error instead. Getting
    # RuntimeError back is what says nothing left the process.
    url = make_url(settings.DATABASE_URL).set(host="a-host-that-does-not-resolve.invalid")
    engine = create_async_engine(url.render_as_string(hide_password=False))
    try:
        with pytest.raises(RuntimeError, match="non-test database"):
            async with engine.connect():
                pass
    finally:
        await engine.dispose()


async def test_the_maintenance_engine_connects_when_database_url_names_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The same unresolvable host as above: a DNS failure, not RuntimeError, is
    # what says the guard let the maintenance engine through to the driver.
    monkeypatch.setattr(settings, "DATABASE_URL", "postgresql+asyncpg://localhost:5432/postgres")
    url = make_url(settings.TEST_DATABASE_URL).set(host="a-host-that-does-not-resolve.invalid", database="postgres")
    engine = create_async_engine(url.render_as_string(hide_password=False))
    allow_maintenance_engine(engine)
    try:
        with pytest.raises(OSError):
            async with engine.connect():
                pass
    finally:
        await engine.dispose()
