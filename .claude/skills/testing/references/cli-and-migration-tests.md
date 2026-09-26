# CLI tests, migration-body tests, and the two session-scope gotchas

Open this before writing a CLI test, a migration-body test, or a session-scoped fixture that has to swap an attribute.

## The `cli/conftest.py` fixtures

- **`no_server`** — fails the test if anything reaches the transport. The default for a CLI test that should never leave the process.
- **`live_server`** — the app under uvicorn on an ephemeral port, behind a proxy that stalls, redirects, or 413s on `x-test-proxy`. It binds the session source to the test engine for the server's lifetime through `bind_session_source` and reads the binding back, so a missing binding fails at setup; unbound, a leak would reach the non-test database named by `DATABASE_URL`. `install_non_test_database_guard()` (`tests/_non_test_database.py`, armed in `tests/conftest.py`) refuses that connection in every run, and CI's unreadable `DATABASE_URL` is the second line of defense.
- **`socket_client`** — the client `a11y` ships, pointed at that server, over the production `AsyncHTTPTransport`.
- **`forwarded`** — what the proxy in front of `live_server` actually saw.

`test_live_server.py` is what exercises the pair end to end: one ingest, one import, a read timeout, a redirect, and the proxy's 413 on a large POST.

## Migration-body tests (`tests/migrations/test_<revision>.py`)

Run a shipped `upgrade()`/`downgrade()` bound to `db_session` through `harness.py`. Restore the pre-migration schema via the shipped `downgrade()` — hand-written DDL only when the needed downgrade is irreversible, and then with the reason stated in place. `test_rederive_app_slugs.py` is the worked example of driving an `upgrade()`; `test_single_root_org_unit_index.py` is the one for restoring through a `downgrade()`.

`test_downgrade_floor.py` is the odd one out in this directory: it needs no database, reads `DOWNGRADE_FLOOR` out of the `Makefile`, resolves it through alembic, and fails if it resolves to the head, however the value is spelled.

## `deadlock_timeout` is superuser-set

The `engine` fixture sets `deadlock_timeout = 50ms` on every connection. Don't re-set the GUC per test; raise it with `SET LOCAL`, for one transaction, only to steer which backend Postgres picks as the deadlock victim, the way `test_rollup_deadlock.py` does. A plain `SET` survives a commit and returns to the pool with its connection, where a later deadlock test's waiter would arm the raised check instead of 50 ms.

Dev and CI connect as superuser, and the setting rides the connection startup packet, so a non-superuser test role fails **every** connection with `FATAL: permission denied to set parameter`. The escape hatch is `GRANT SET ON PARAMETER deadlock_timeout TO <role>`.

## Swapping an attribute from a session-scoped fixture

`monkeypatch` and `mocker` are both function-scoped, so a session-scoped fixture cannot request either. For the session source, wrap the fixture's `yield` in `bind_session_source`, a context manager that restores the previous source on exit, as `tests/cli/conftest.py`'s `live_server` does. For any other attribute, wrap the `yield` in a `pytest.MonkeyPatch.context()`; no fixture in the suite needs one today.
