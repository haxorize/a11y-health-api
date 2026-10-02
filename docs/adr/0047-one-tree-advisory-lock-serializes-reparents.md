# One tree-wide advisory lock serializes Org Unit reparents

This amends [ADR 0029](0029-per-owner-advisory-lock-rollup-serialization.md) by placing one lock ahead of its rollup locks, and [ADR 0026](0026-single-root-org-unit-invariant.md) by closing the concurrent-reparent gap its 2026-09-26 (#163) entry names.

`update_org_unit` checks that the proposed parent is outside the unit's subtree and then writes the new `parent_id`. Under READ COMMITTED, two concurrent reparents that close a loop each pass that check against the committed tree and both commit, leaving an Org Unit cycle (#176). A PATCH that carries `parent_id`, null included, therefore acquires a transaction-scoped advisory lock on the single key `reparent:org_unit_tree`, hashed with `hashtextextended` as ADR 0029's keys are, as its first statement. The lock comes before the unit is loaded, so `old_parent_id`, the ancestry check, and the write all read the tree as the previous reparent committed it. Taking it before the load also closes a second race: when two requests reparent the same unit, the second would otherwise read `old_parent_id` from before the first committed, and run the old parent's Org Unit Rollup against the wrong unit.

The loser waits, then runs its check against the winner's committed tree. If its move would now close a cycle it fails with the existing `CircularReferenceError`, 409 `circular_reference`, which is not retryable, because a retry reads the same tree and gets the same answer. Otherwise it succeeds. No error mode is added, so the contract does not move.

Lock order: the tree lock first, then the reparented unit's row lock ([ADR 0048](0048-scan-run-row-lock-serializes-completion-and-page-adds.md) gives the full order), then ADR 0029's per-owner rollup locks, which the reparent's two cascades take after the write. Outside a hash collision, no transaction takes a rollup lock and then waits on the tree lock, so the tree lock adds no deadlock; the deadlocks ADR 0029 accepts between cascades are unchanged and still surface as `concurrent_rollup`. A collision between the tree key and some rollup key, at odds of about 2^-64 per rollup key, does more than over-serialize. The reparent's own cascade re-enters the colliding key without waiting, but a concurrent cascade holding a rollup lock the reparent still needs can wait on the colliding key while the reparent's cascade waits on that rollup lock. PostgreSQL detects that deadlock and fails one side, and because both waits sit in `_acquire_rollup_lock`, the loser gets the retryable `concurrent_rollup` as well.

The lock guards acyclicity and nothing else. Creating, renaming, and deleting an Org Unit do not take it, because none of them can close a cycle, and extending it to them would make every Org Unit write wait on every reparent. Every reparent in the tree runs one at a time and holds the lock through its cascades; reparents are rare operator actions, and that wait is accepted.

Considered and rejected:

- **Row locks on the reparented unit and the proposed parent's ancestor chain:** every chain ends at the Root Org Unit (ADR 0026), so this locks the root row on every reparent and serializes as much as the tree lock does, with a second kind of lock ahead of the cascade. A plain `FOR UPDATE` would also stall every other transaction's insert that references a locked unit, such as a concurrent cascade's Score Snapshot or a new App, since those foreign keys take `KEY SHARE` on the same rows. The reparent's own inserts would not wait, because a transaction never waits on a lock it holds.
- **A trigger that refuses a cycle:** a trigger walking ancestors under READ COMMITTED races exactly as the Python check does, so it is sound only if it takes a lock itself. It would then be this decision plus a migration, a PL/pgSQL walk, and a second failure path to map through the Integrity Guard. Its one gain is holding against writers outside the application, and `update_org_unit` is the only code that changes an existing unit's `parent_id`. `create_org_unit` and the seed migration set it on insert, which cannot close a cycle, because a new unit has no descendants.

The walks and the Org Unit Rollup keep #163's guards against a committed cycle, since a cycle committed before this lock, or by a writer outside the application, still reaches them.

## Deferred

- A database-level cycle backstop, reopened when a writer outside the application appears: a bulk import, or a runbook that edits `parent_id` in SQL.

Revisit when: a second code path changes an existing unit's `parent_id`, or reparents become frequent enough that serializing them across the tree is felt.
