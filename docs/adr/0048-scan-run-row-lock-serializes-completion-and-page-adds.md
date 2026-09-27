# A row lock on the Scan Run serializes completion and page adds

This amends [ADR 0029](0029-per-owner-advisory-lock-rollup-serialization.md) by placing one lock ahead of its rollup locks.

`update_scan_run_status` checks the transition in Python and then writes the status. Under READ COMMITTED, two concurrent completions of one Pending run both pass that check. The second status UPDATE waits on the first's row lock, proceeds once it commits, and its App Score Snapshot insert violates `uq_score_snapshot_scan_run_id`, which surfaces as an undeclared 500 (#178). `create_page_result` has the same shape: its status check reads a Pending run, so a page arriving mid-completion lands on a Completed run with no Page Health and is never scored.

Completion therefore reads the Scan Run with `SELECT … FOR UPDATE`, and a page add reads it with `FOR SHARE`, each before its status check. A second completion waits, reads Completed, and fails with the existing `InvalidStatusTransitionError`, 409 `invalid_status_transition`. A page add that arrives mid-completion waits and fails with the existing `ScanRunCompletedError`, 409 `scan_run_completed`. Neither is retryable, because a retry reads the same Completed run and gets the same answer. Concurrent page adds share the lock and still run together. No error mode is added, so the contract does not move.

Lock order: the Scan Run row first, then ADR 0029's per-owner rollup locks, which the completion cascade takes after the write. That was already the order, since the status UPDATE took this row lock before the cascade; the lock moves earlier in the same transaction and adds no edge. No transaction takes a rollup lock and then waits on a Scan Run row: Scan Run deletion and App deletion both lock their rows before their cascades.

The line between this lock and the Integrity Guard (ADR 0028) is what decides the race. The guard answers a race a constraint decides, such as a write that references an Org Unit deleted underneath it, which #178 maps to `NotFoundError` at the App and Org Unit write sites. The Existence Guard builds that error for the mapping, which amends [ADR 0024](0024-existence-guard-core-module-two-tier-rule.md)'s single raise site into a single construction site. A check-then-act on a row's own state has no deciding constraint: the snapshot uniqueness violation is a side effect several calls past the check, and nothing catches the page-add race at all. That kind of race takes a row lock.

Considered and rejected:

- **Mapping `uq_score_snapshot_scan_run_id` through the Integrity Guard:** the loser rewrites Page Health and attempts a snapshot before it is refused, the guard has to wrap the whole scoring and rollup call, and its 409 infers a status nobody read. It also cannot close the page-add race, since no constraint is violated there.
- **A conditional UPDATE on `status = 'pending'`:** it takes the same row lock, but at the write, so the transition check and the empty-run check read state no lock holds. Locking at the read makes every check see the state the write acts on.

Revisit when: a Scan Run gains a second status transition, or a code path takes a rollup lock and then writes a Scan Run.
