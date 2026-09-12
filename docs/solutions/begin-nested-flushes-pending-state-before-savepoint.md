---
title: "begin_nested() flushes pending state before emitting SAVEPOINT, so the savepoint never guards it"
problem_type: database_issue
tags: [sqlalchemy, savepoint, begin-nested, flush, integrity-error, transaction, asyncpg]
symptoms:
  - "PendingRollbackError: This Session's transaction has been rolled back due to a previous exception during flush"
  - "session unusable after catching IntegrityError from a flush wrapped in begin_nested()"
  - "savepoint did not keep the outer transaction usable after a caught constraint violation"
root_cause: "SessionTransaction._take_snapshot runs an unconditional session.flush() when begin_nested() starts, so writes already pending at entry are flushed BEFORE the SAVEPOINT exists and a violation escapes it, poisoning the whole transaction"
module: core/integrity
date: 2026-07-12
---

# begin_nested() flushes pending state before emitting SAVEPOINT, so the savepoint never guards it

## Problem

Services used `session.add(obj)` followed by `try: async with session.begin_nested(): await session.flush()` to translate an `IntegrityError` into a domain error "while keeping the transaction usable." The `except` worked (the error still raises inside the `try`), but the savepoint guarantee was silently dead: after a caught violation the next session use raised `PendingRollbackError`. Nothing exercised the post-catch session, so the gap was invisible until a test asserted it.

## What didn't work

- **Suppressing the pre-flush with `no_autoflush`** — the flush at nested-begin is `SessionTransaction._take_snapshot`'s unconditional `session.flush()` (gated only on `not session._flushing`), not an autoflush; the flag is ignored.
- **Assuming the docs' skip-duplicates pattern covers this shape** — the documented pattern puts the mutation *inside* the `begin_nested` block, where the failing INSERT runs under the savepoint. With the mutation added *before* the block, the pre-flush executes it unprotected; the explicit inner `flush()` never even runs (verified with a probe flag).
- **Suspecting the test fixture's `join_transaction_mode="create_savepoint"`** — a plain production-shaped session reproduced identically; the fixture was not load-bearing.

## Fix

Made the guarded-write helper an async context manager so the mutation happens inside the savepoint scope (`core/integrity.py::guard`): begin_nested first, `yield` for the caller's `session.add(...)`/attribute sets, then an explicit `flush()` before the savepoint releases. A caught violation now rolls back only the savepoint and the surrounding transaction stays usable. (Same change also switched constraint matching to asyncpg's parsed `constraint_name` instead of message text.)

## Prevention

- `tests/core/test_integrity.py::test_transaction_stays_usable_after_caught_violation` pins the guarantee; `test_mutation_outside_guard_would_not_be_protected` pins the sharp edge itself, so if SQLAlchemy ever changes the pre-flush behavior the pin fails and the constraint can be revisited.
- The fastapi convention skill's Services section now mandates `integrity.guard` with the mutation inside the block; no service hand-rolls `begin_nested`.
- Beware when reading green tests as proof: a conflict test that ends at the expected 409 never checks that the session survived it.
