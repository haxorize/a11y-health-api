# Fixture fidelity limits

## `db_client` never ends the request's transaction

The session source `db_client` binds yields `db_session` and stops there, where production's `get_db` commits on success and rolls back on an exception. So a row a handler flushed before raising a 4xx stays visible for the rest of the test, where production would have discarded it. That is a fidelity limit to test around, not a bug: ADR 0011's rollback isolation is why that source is shaped this way. Assert the rejection itself — a follow-up read through `db_client` cannot tell you what production kept.
