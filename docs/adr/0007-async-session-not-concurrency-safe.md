# Service code does not run concurrent awaits on a shared AsyncSession

SQLAlchemy's `AsyncSession` is not safe for concurrent use. Two awaits on the same session can raise `InvalidRequestError: Session is already flushing` or silently corrupt state. The test fixture `db_client` overrides FastAPI's `get_db` to yield a single shared `AsyncSession` so tests can assert DB state, which means concurrent HTTP requests through `db_client` also fail for the same reason.

Service modules must therefore await DB calls **sequentially** when they share a session. This is the rule for every helper in `services/*.py` (rollup cascades, score computation, latest-snapshot pairs, persistence loops) and for any client-side code whose tests run through `db_client` (the CLI's per-page POST loop is the canonical trap).

Considered and rejected:
- **`asyncio.gather` over service helpers**: proposed and reverted at least four or five times. The perf gain is real on paper, invisible to type checkers, and detected only when tests run.
- **One session per request in tests**: the legitimate fix, but it removes the test affordance of asserting state through the same session that serviced the request. If the perf is ever genuinely worth it, that's the prerequisite — not a sneaked-in `gather`.

If a refactor introduces parallel awaits, trace each call's `session` parameter: if any two share a session (or both route through `db_client` in tests), keep them sequential.

**Amendment (2026-09-12, #147).** This record presupposes the fully async stack rather than deciding it. That choice is [ADR 0045](0045-fully-async-stack-unexamined.md), which records it as never having been examined — so reopening async is reopening this record too, not just that one.

**Amendment (2026-09-26, #161).** The mechanism moved and the decision did not. `db_client` no longer overrides `get_db`: it binds the session source (`bind_session_source` in `core/database.py`) to one that hands every request the same shared `db_session`, with no commit and no rollback, so the concurrency hazard above applies unchanged. The source is one module-level object rather than a factory on the application's state, the other shape #161 weighed, so the dependency and the startup probe read the same name that every test rebinds, and only `bind_session_source` rebinds it.
