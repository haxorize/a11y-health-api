"""Refuses any connection this suite opens to the non-test database.

`DATABASE_URL` names the database the application serves from. Outside CI that
is `config.py`'s default, `a11y_health` on localhost, the developer's real
database, and the pre-commit hook runs this suite on every commit with the
developer's `.env` copied in. A fixture that leaked to that setting would write
to real data once per commit, and pass while doing it.

The seam is `do_connect` because it fires *before* the DBAPI connect and carries
the resolved database name: `engine_connect` fires only after a connection is
open, and not at all when the database is absent, so it can report a leak but
cannot refuse one.
"""

from typing import Any
from weakref import WeakSet

from sqlalchemy import event
from sqlalchemy.engine import Dialect, Engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncEngine

from a11y_health.config import settings

_MAINTENANCE: WeakSet[Dialect] = WeakSet()


def forbidden_database() -> str:
    # Read from `settings` at call time rather than captured at import, so a
    # test that swaps the setting is measured against what it swapped it to.
    return make_url(settings.DATABASE_URL).database or ""


def refuse_non_test_database(database: str | None) -> None:
    """Exact match, not a prefix: the per-run test database is the test
    template's name plus the pid (`a11y_health_test_8123`), and a prefix test
    over `a11y_health` would refuse every run of the suite.

    Raises:
        RuntimeError: `database` is the one `DATABASE_URL` names, or
            `DATABASE_URL` names none. The driver then falls back to
            `PGDATABASE` or the user's name, which could be the real database
            and cannot be compared, so the guard refuses rather than guess.
    """
    forbidden = forbidden_database()
    if not forbidden:
        raise RuntimeError(
            "DATABASE_URL names no database, so the non-test-database guard "
            "cannot tell which connection to refuse. Name one in the URL."
        )
    if database == forbidden:
        raise RuntimeError(
            f"a test opened a connection to {database!r}, the non-test database "
            f"named by DATABASE_URL. Nothing in this suite may read it: outside "
            f"CI that is real data, and the pre-commit hook runs this suite on "
            f"every commit. Bind the fixture to the `engine` fixture's test "
            f"database instead — tests/cli/conftest.py's live_server is the "
            f"worked example (ADR 0011)."
        )


def install_non_test_database_guard() -> None:
    """Registered on the `Engine` class rather than on one engine object,
    because the leak this catches is code reaching `core.database`'s
    module-level engine *or* building its own from the same setting, and
    pinning one object would see only the first.
    """
    if event.contains(Engine, "do_connect", _refuse_on_connect):
        return
    event.listen(Engine, "do_connect", _refuse_on_connect)


def allow_maintenance_engine(engine: AsyncEngine) -> None:
    """Exempts the engine that creates and drops the per-run test database.
    It connects to `postgres`, and a `DATABASE_URL` naming `postgres` would
    otherwise leave the suite unable to build its own database.
    """
    _MAINTENANCE.add(engine.sync_engine.dialect)


def _refuse_on_connect(dialect: Any, conn_rec: Any, cargs: Any, cparams: dict[str, Any]) -> None:
    # Returning None lets the connect proceed normally; raising stops it before
    # a socket is opened, which is what makes this a refusal rather than a
    # report. `cparams` is what the dialect is about to hand the driver, so it
    # holds the database actually being connected to after every URL default
    # has been resolved.
    if dialect in _MAINTENANCE:
        return
    refuse_non_test_database(cparams.get("database"))
