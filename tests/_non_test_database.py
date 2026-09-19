"""Refuses any connection this suite opens to the non-test database.

CI's test job points `DATABASE_URL` at `a11y_health_must_not_be_read`, a
database its service container never creates, so a fixture that leaks to the
non-test setting fails to connect there instead of passing quietly against the
test database. That is the whole of the invariant today, and it lives in one
`env:` value in one job.

Everywhere else the same leak is silent and destructive. `.env` is gitignored
and currently activates nothing, so `DATABASE_URL` falls back to `config.py`'s
default — `a11y_health` on localhost, the developer's real database — and the
pre-commit hook runs this suite on every commit with that `.env` copied in. A
leaked fixture writes to real data once per commit, and the only check that
would have caught it is a string in a file the hook never reads.

So the invariant moves here, where every run reads it rather than one job. The
seam is `do_connect` because it fires *before* the DBAPI connect and carries
the resolved database name: `engine_connect` fires only after a connection is
open, and not at all when the database is absent, so it can report a leak but
cannot refuse one.
"""

from typing import Any

from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.engine.url import make_url

from a11y_health.config import settings


def forbidden_database() -> str:
    """The database name no connection from this suite may name.

    Read from `settings` at call time rather than captured at import, so a test
    that swaps the setting is measured against what it swapped it to.
    """
    return make_url(settings.DATABASE_URL).database or ""


def refuse_non_test_database(database: str | None) -> None:
    """Raises when `database` is the non-test one. The whole rule, callable.

    Exact match, not a prefix: the per-run test database is the test template's
    name plus the pid (`a11y_health_test_8123`), and a prefix test over
    `a11y_health` would refuse every run of the suite.
    """
    forbidden = forbidden_database()
    if forbidden and database == forbidden:
        raise RuntimeError(
            f"a test opened a connection to {database!r}, the non-test database "
            f"named by DATABASE_URL. Nothing in this suite may read it: outside "
            f"CI that is real data, and the pre-commit hook runs this suite on "
            f"every commit. Bind the fixture to the `engine` fixture's test "
            f"database instead — tests/cli/conftest.py's live_server is the "
            f"worked example (ADR 0011)."
        )


def install_non_test_database_guard() -> None:
    """Arms the rule for the whole session, on every engine the suite builds.

    Registered on the `Engine` class rather than on one engine object, because
    the leak this catches is code reaching `core.database`'s module-level
    engine *or* building its own from the same setting, and pinning one object
    would see only the first.
    """
    if event.contains(Engine, "do_connect", _refuse_on_connect):
        return
    event.listen(Engine, "do_connect", _refuse_on_connect)


def _refuse_on_connect(dialect: Any, conn_rec: Any, cargs: Any, cparams: dict[str, Any]) -> None:
    # Returning None lets the connect proceed normally; raising stops it before
    # a socket is opened, which is what makes this a refusal rather than a
    # report. `cparams` is what the dialect is about to hand the driver, so it
    # holds the database actually being connected to after every URL default
    # has been resolved.
    refuse_non_test_database(cparams.get("database"))
