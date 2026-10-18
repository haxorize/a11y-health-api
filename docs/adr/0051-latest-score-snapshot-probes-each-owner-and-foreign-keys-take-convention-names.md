# The Latest Score Snapshot probes each Owner, and foreign keys take convention names

The Latest Score Snapshot is read by a per-Owner `LATERAL` probe rather than a ranked window, `score_snapshot` gains one App composite index to serve it, and `Base.metadata` declares a naming convention under which the six unnamed foreign keys are renamed. Every consumer gets the same rows in the same order; fewer rows are read to produce them, and six constraints carry new names. Decided 2026-10-18 in the grill that [#182](https://github.com/haxorize/a11y-health-api/issues/182) asked for.

## The read shape

The helper in `services/_latest_snapshot.py` ranked every snapshot in its partition set with `row_number()` and kept rank 1. A window function is a blocking node, so the outer `LIMIT` of a `/scores/latest` page could not stop it: the 2026-09-05 audit's finding P6-01 planned the first App page as a sequential scan, a sort and a `WindowAgg` over every App snapshot ever written, repeated on every page and on every rollup's children read. [ADR 0015](0015-score-snapshot-append-only.md) makes that set grow by one row per completed Scan Run, without bound.

The helper now starts from a select of Owner ids and, for each, probes the newest row with `ORDER BY snapshot_at DESC, id DESC LIMIT 1` inside a `LATERAL` subquery. A page then costs one index probe per Owner on the page. The helper's arguments change to match: it takes one Owner column and a select of that Owner type's ids, where it took a select of snapshots, because a probe that starts from snapshots walks them all again. `list_latest_scores` draws its ids from the Owner's own table, with the scope predicates applied to that table's `id`. `_latest_child_snapshots` is two probes joined by `UNION ALL`, one over the Org Unit's Apps and one over its child Org Units. With one column per probe, the rule that owner ids from separate sequences are never coalesced into one partition holds by construction instead of by a filter. An Owner with no snapshot yields no row, as before.

Two alternatives were weighed and refused. `DISTINCT ON (owner) ... ORDER BY owner, snapshot_at DESC, id DESC` is the shorter rewrite, but PostgreSQL 15 has no loose index scan, so it still reads every row in the set and only drops the sort. The composite index alone was tested too: the audit ran `EXPLAIN` with the index in place and the window kept, and the scan became an index-only scan that still fed every row to the same `WindowAgg`.

The probe's ordering lives only in `_latest_snapshot.py`, which is what keeps the one definition [ADR 0023](0023-scores-latest-read-endpoint.md) requires. A caller that writes its own probe splits that definition. Each caller's driving select owns its own scope, as each caller's snapshot select did before; a mechanical guard was weighed and not taken, because a scan for `snapshot_at.desc()` also hits `list_scores`' keyset ordering and would need an allowlist from the start.

## The index

`ix_score_snapshot_app_id` is replaced by `ix_score_snapshot_app_id_snapshot_at_id` on `(app_id, snapshot_at DESC, id DESC)`, neither unique nor partial, since an App may hold two snapshots at one Observation Time. `app_id` stays leading, so the CASCADE check from `app` and the rollup's `DELETE ... WHERE app_id` keep an index. A backward scan of the same index serves `list_scores`' ascending App history. The Org Unit and Brand Owners already carry the `(owner_id, snapshot_at)` partial unique indexes of ADR 0015; they allow no tie, so they serve the probe without an `id` column and are left as they are.

The `scan_run (app_id, scanned_at, id)` composite stays out. [ADR 0017](0017-keyset-pagination-deep-module.md) defers it until a high-volume App's history latency justifies it, and that trigger has not fired; a migration being written anyway was not taken as a reason.

## The naming convention

`Base.metadata` declares a naming convention with `fk`, `uq` and `ix` keys only. Its `fk` template, `fk_%(table_name)s_%(column_0_name)s`, reproduces the five explicit foreign key names exactly, so the six foreign keys that carried PostgreSQL's default `<table>_<column>_fkey` are renamed to it: `node_finding.rule_finding_id`, `rule_finding.page_result_id`, `page_result.scan_run_id`, `scan_run.app_id`, `score_snapshot.app_id` and `score_snapshot.scan_run_id`. The renames use `ALTER TABLE ... RENAME CONSTRAINT`, the form migration `e8dedf017569` used, which changes the catalog and validates no row. The `uq` and `ix` keys rename nothing that exists, because every unique constraint and index in the models already carries an explicit name, and an explicit name takes precedence over the convention; they name only what is declared later without one. The migration's downgrade restores `ix_score_snapshot_app_id` and the six default names. None of the six is mapped by [ADR 0028](0028-integrity-guard-constraint-identity-savepoint.md)'s integrity guard, so no 409 classification moves.

The `ck` and `pk` keys are left out on purpose. Every explicit check name already carries its `ck_<table>_` prefix, and a `ck_%(table_name)s_%(constraint_name)s` template would double it into `ck_app_ck_app_name_length`. Alembic's autogenerate never compares primary key names, so a `pk` key would have the model say `pk_app` while the database holds `app_pkey`, and no check would see the split. The five explicit names and their `FK_*` constants stay as written: ADR 0028's mappings import those constants, and the convention producing the same string is no reason to drop them.

## The guard on constraint names

Alembic 1.18 compares foreign keys by their columns and referent and ignores the name, so the drift check cannot see a rename that was missed. A test in `tests/migrations/` reads every foreign key name from `pg_constraint` at the head and fails on one that differs from the name `Base.metadata` gives it.

## Consequences

A later `ck` key needs every explicit check name wrapped in SQLAlchemy's `conv()`, which marks a name as already converted, or shortened to its suffix, in a migration of its own. `list_scores` reads one Owner's history and has no window to remove, so the probe is not a pattern it takes.

## Deferred

- The plan evidence is open until #182 is implemented. That change runs `EXPLAIN (ANALYZE)` on the first App page before and after, on the `verify` skill's scratch database seeded to the audit's volume (100 Apps, 2,320 snapshots), and quotes both plans here. The after plan has to show no node whose row count equals the table's.

Revisit when: a Latest Score Snapshot consumer has no Owner set to drive a probe from, or the PostgreSQL major in use can stop a `DISTINCT ON` read early.
