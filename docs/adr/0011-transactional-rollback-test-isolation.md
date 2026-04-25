# Test isolation via outer-transaction rollback with savepoint nesting

The `db_session` fixture opens a connection, begins an outer transaction, and
hands tests an `AsyncSession` bound to that connection with
`join_transaction_mode="create_savepoint"`. On teardown the outer transaction
is rolled back, undoing every write a test made — including writes that the
service code "committed," which become savepoint releases inside the outer
transaction. The `db_client` fixture overrides FastAPI's `get_db` to yield this
single session, so HTTP requests in tests share the same rollback boundary.

Considered and rejected:
- **Truncate (or drop+recreate) tables between tests**: simpler to reason
  about, but slow at scale and forces every test to re-seed reference data.
  Also wouldn't give us the affordance of asserting state through the same
  session that serviced the request.
- **Per-test schema (template DBs, transactional DDL)**: heavier than needed
  for an internal service, and turns connection setup into the dominant test
  cost.

Two consequences worth keeping in mind:
- Service code that `commit`s still works — commits become savepoint releases.
- The same shared session that makes tests fast also makes concurrent awaits
  unsafe inside tests, which is why ADR-0007 exists.
