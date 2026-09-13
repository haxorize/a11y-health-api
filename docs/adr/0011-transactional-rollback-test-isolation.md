# Test isolation via outer-transaction rollback with savepoint nesting

> **Amended by #137:** a second class joins the sanctioned exception below. `tests/cli/conftest.py`'s `live_server` serves the app over a real socket, and a server's requests run on their own connections, so they cannot join a test's rolled-back transaction any more than a lock-contention test can. It binds the production sessionmaker to the test engine for the server's lifetime, and every test that writes through it takes `committed_session_factory` for the same truncate at teardown. Both classes share one rule: real commits are scoped to the tests that need them.

The `db_session` fixture opens a connection, begins an outer transaction, and hands tests an `AsyncSession` bound to that connection with `join_transaction_mode="create_savepoint"`. On teardown the outer transaction is rolled back, undoing every write a test made — including writes that the service code "committed," which become savepoint releases inside the outer transaction. The `db_client` fixture overrides FastAPI's `get_db` to yield this single session, so HTTP requests in tests share the same rollback boundary.

Considered and rejected:
- **Truncate (or drop+recreate) tables between tests**: simpler to reason about, but slow at scale and forces every test to re-seed reference data. Also wouldn't give us the affordance of asserting state through the same session that serviced the request.
- **Per-test schema (template DBs, transactional DDL)**: heavier than needed for an internal service, and turns connection setup into the dominant test cost.

Two consequences worth keeping in mind:
- Service code that `commit`s still works — commits become savepoint releases.
- The same shared session that makes tests fast also makes concurrent awaits unsafe inside tests, which is why ADR-0007 exists.

One sanctioned exception: a test whose point is that one transaction's state must be visible to another (genuine advisory-lock contention, e.g. the full-stack deadlock test from #110) cannot run inside a single rolled-back transaction. The `committed_session_factory` fixture serves those tests with real commits on separate connections and pays the rejected truncate cost on teardown — scoped to only the tests that need it.

**Amendment (2026-09-12, #147).** This record presupposes the fully async stack rather than deciding it. That choice is [ADR 0045](0045-fully-async-stack-unexamined.md), which records it as never having been examined — so reopening async is reopening this record too, not just that one.
