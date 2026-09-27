# CLI tests, migration-body tests, `deadlock_timeout`, and session-scoped fixtures

Open this before writing a CLI test, a migration-body test, or a session-scoped fixture that has to swap an attribute.

## The `cli/conftest.py` fixtures

- **`no_server`** — fails the test if anything reaches the transport. The default for a CLI test that should never leave the process.
- **`live_server`** — the app under uvicorn on an ephemeral port, behind a proxy that stalls, redirects, or 413s on `x-test-proxy`. It binds the session source to the test engine for the server's lifetime through `bind_session_source` and reads the binding back, so a missing binding fails at setup; unbound, a leak would reach the non-test database named by `DATABASE_URL`. `install_non_test_database_guard()` (`tests/_non_test_database.py`, armed in `tests/conftest.py`) refuses that connection in every run, and CI's unreadable `DATABASE_URL` is the second line of defense.
- **`socket_client`** — the client `a11y` ships, pointed at that server, over the production `AsyncHTTPTransport`.
- **`forwarded`** — what the proxy in front of `live_server` actually saw.

`test_live_server.py` is what exercises the pair end to end: one ingest, one import, a read timeout, a redirect, and the proxy's 413 on a large POST.

## Migration-body tests (`tests/migrations/test_<revision>.py`)

Load the revision under test with `load_migration(<id>)`, taking the id from the named constants in `harness.py`, and call `restore_pre_migration_schema(db_session, <id>)`: it runs every shipped `downgrade()` from the head down to and including that revision, inside the rolled-back `db_session`. A downgrade that raises stops the walk with `IrreversibleRevisionError`; name that revision in `skips` only if it changes no schema the test exercises, with the reason stated in the test's docstring, and a `skips` entry the walk no longer needs raises `StaleSkipError`. The schema is genuinely older while `tests/factories.py` builds head-schema rows, so seed through raw SQL wherever the walk undid a change to a table you seed. Then drive the body with `run_upgrade`. `test_rederive_app_slugs.py` is the worked example of a walk with `skips`; `test_single_root_org_unit_index.py` is the one without a data-only crossing of its own.

`test_downgrade_floor.py` is the odd one out in this directory: it reads `DOWNGRADE_FLOOR` out of the `Makefile` through `roundtrip.downgrade_floor()`, resolves it through alembic, and fails if it resolves to the head, however the value is spelled. Its roundtrip test owns the outcome of the session-scoped `roundtrip` fixture, which runs upgrade, downgrade to the floor, and upgrade again in one child process over a per-run database of its own, once per session. Any other reader takes `migrated_database_url`, which fails with the child's stderr rather than hand over a half-migrated database.

`test_check_constraints.py` reads the head that roundtrip leaves and compares every check constraint with the one the models' metadata builds in the `engine` fixture's database, since Alembic's autogenerate compares no check-constraint text. A new reader of the migrated schema takes the `roundtrip` fixture rather than starting a child of its own: each interpreter costs its imports again, per commit.

## `deadlock_timeout` is superuser-set

The `engine` fixture sets `deadlock_timeout = 50ms` on every connection. Don't re-set the GUC per test; raise it with `SET LOCAL`, for one transaction, only to steer which backend Postgres picks as the deadlock victim, the way `test_rollup_deadlock.py` does. A plain `SET` survives a commit and returns to the pool with its connection, where a later deadlock test's waiter would arm the raised check instead of 50 ms.

Dev and CI connect as superuser, and the setting rides the connection startup packet, so a non-superuser test role fails **every** connection with `FATAL: permission denied to set parameter`. The escape hatch is `GRANT SET ON PARAMETER deadlock_timeout TO <role>`.

## Swapping an attribute from a session-scoped fixture

`monkeypatch` and `mocker` are both function-scoped, so a session-scoped fixture cannot request either. For the session source, wrap the fixture's `yield` in `bind_session_source`, a context manager that restores the previous source on exit, as `tests/cli/conftest.py`'s `live_server` does. For any other attribute, wrap the `yield` in a `pytest.MonkeyPatch.context()`; no fixture in the suite needs one today.
