# The Latest Score Snapshot probes each Owner, and foreign keys take convention names

The Latest Score Snapshot is read by a per-Owner `LATERAL` probe rather than a ranked window, an App composite index on `score_snapshot` replaces its App index to serve it, and `Base.metadata` declares a naming convention under which the six unnamed foreign keys are renamed. Every consumer gets the same rows in the same order; fewer rows are read to produce them, and six constraints carry new names. Decided 2026-10-18 in the grill that [#182](https://github.com/haxorize/a11y-health-api/issues/182) asked for.

## The read shape

The helper in `services/_latest_snapshot.py` ranked every snapshot in its partition set with `row_number()` and kept rank 1. A window function is a blocking node, so the outer `LIMIT` of a `/scores/latest` page could not stop it: the 2026-09-05 audit's finding P6-01 planned the first App page as a sequential scan, a sort and a `WindowAgg` over every App snapshot ever written, repeated on every page and on every rollup's children read. [ADR 0015](0015-score-snapshot-append-only.md) makes that set grow by one row per completed Scan Run, without bound.

The helper now selects from the Owner's own table and, for each Owner row, probes the newest snapshot with `ORDER BY snapshot_at DESC, id DESC LIMIT 1` inside a `LATERAL` subquery. A page then costs one index probe per Owner on the page. The helper's arguments change to match: it takes the Owner's `OWNERS` entry, which pairs the Owner entity with that Owner's column on `score_snapshot` so the two cannot be mismatched, where it took a select of snapshots, because a probe that starts from snapshots walks them all again. Each caller narrows the Owners with `.where()` on the Owner table's columns. `list_latest_scores` pages on the Owner table's `id`, a primary key, instead of the nullable owner column on `score_snapshot`; the planner stops the walk at the page's `LIMIT` only when the order is on the driving table. With no caller left paging a nullable column, `paginate` now refuses one at entry, as [ADR 0017](0017-keyset-pagination-deep-module.md)'s 2026-10-18 entry records. That was taken in the same change at the user's direction rather than left deferred. `_latest_child_snapshots` is two probes joined by `UNION ALL`, one over the Org Unit's Apps and one over its child Org Units. With one column per probe, the rule that owner ids from separate sequences are never coalesced into one partition holds by construction instead of by a filter. An Owner with no snapshot yields no row, as before.

Two alternatives were weighed and refused. `DISTINCT ON (owner) ... ORDER BY owner, snapshot_at DESC, id DESC` is the shorter rewrite, but PostgreSQL 15 has no loose index scan, so it still reads every row in the set and only drops the sort. The composite index alone was tested too: the audit ran `EXPLAIN` with the index in place and the window kept, and the scan became an index-only scan that still fed every row to the same `WindowAgg`.

The probe's ordering lives only in `_latest_snapshot.py`, which is what keeps the one definition [ADR 0023](0023-scores-latest-read-endpoint.md) requires. A caller that writes its own probe splits that definition. Each caller's driving select owns its own scope, as each caller's snapshot select did before; a mechanical guard was weighed and not taken, because `list_scores` orders by the same `snapshot_at, id` pair through `paginate`'s keyset, so a guard keyed on that ordering would need an allowlist from the start.

## The index

`ix_score_snapshot_app_id` is replaced by `ix_score_snapshot_app_id_snapshot_at_id` on `(app_id, snapshot_at DESC, id DESC)`, neither unique nor partial, since an App may hold two snapshots at one Observation Time. `app_id` stays leading, so the CASCADE check from `app` keeps an index. A backward scan of the same index serves `list_scores`' ascending App history. The Org Unit and Brand Owners already carry the `(owner_id, snapshot_at)` partial unique indexes of ADR 0015; they allow no tie, so they serve the probe without an `id` column and are left as they are.

The `scan_run (app_id, scanned_at, id)` composite stays out. [ADR 0017](0017-keyset-pagination-deep-module.md) defers it until a high-volume App's history latency justifies it, and that trigger has not fired; a migration being written anyway was not taken as a reason.

## The naming convention

`Base.metadata` declares a naming convention with `fk`, `uq` and `ix` keys only. Its `fk` template, `fk_%(table_name)s_%(column_0_name)s`, reproduces the five explicit foreign key names exactly, so the six foreign keys that carried PostgreSQL's default `<table>_<column>_fkey` are renamed to it: `node_finding.rule_finding_id`, `rule_finding.page_result_id`, `page_result.scan_run_id`, `scan_run.app_id`, `score_snapshot.app_id` and `score_snapshot.scan_run_id`. The renames use `ALTER TABLE ... RENAME CONSTRAINT`, the form migration `e8dedf017569` used, which changes the catalog and validates no row. The `uq` and `ix` keys rename nothing that exists, because every unique constraint and index in the models already carries an explicit name, and an explicit name takes precedence over the convention; they name only what is declared later without one. The migration's downgrade restores `ix_score_snapshot_app_id` and the six default names. None of the six is mapped by [ADR 0028](0028-integrity-guard-constraint-identity-savepoint.md)'s integrity guard, so no 409 classification moves.

Alembic operations take `target_metadata`'s naming convention, so the convention also reaches the revisions written before it. A historical revision that created a foreign key without a name would now create it under the convention's name, and a later revision that drops it by its default name would fail. The 8 unnamed `ForeignKeyConstraint` entries in revisions `0ef95a6a37d9`, `370cb9cfe3bd`, `7eb59e13902c`, `8dade5d8f0e3` and `f49e037fdb6e` therefore pin PostgreSQL's default name with `op.f()`, which marks a name as final. A fresh database built through the chain holds the same names it held before the convention, and `migrations/env.py` says why.

The `ck` and `pk` keys are left out on purpose. Every explicit check name already carries its `ck_<table>_` prefix, and a `ck_%(table_name)s_%(constraint_name)s` template would double it into `ck_app_ck_app_name_length`. Alembic's autogenerate never compares primary key names, so a `pk` key would have the model say `pk_app` while the database holds `app_pkey`, and no check would see the split. The five explicit names and their `FK_*` constants stay as written: ADR 0028's mappings import those constants, and the convention producing the same string is no reason to drop them.

## The guard on constraint names

Alembic 1.18 compares foreign keys by their columns and referent and ignores the name, so the drift check cannot see a rename that was missed. A test in `tests/migrations/` reads every foreign key name from `pg_constraint` at the head and fails on one that differs from the name `Base.metadata` gives it.

## Consequences

A later `ck` key needs every explicit check name wrapped in SQLAlchemy's `conv()`, which marks a name as already converted, or shortened to its suffix, in a migration of its own. `list_scores` reads one Owner's history and has no window to remove, so the probe is not a pattern it takes.

## The plan evidence

The first App page of `/scores/latest` (`limit=20`, so 21 rows are fetched) was run under `EXPLAIN (ANALYZE, BUFFERS, TIMING OFF, SUMMARY OFF)` on a scratch database built per the `verify` skill and seeded to the audit's volume: 100 Apps with 23 snapshots each, plus 20 Org Unit snapshots on Org Unit 1, 2,320 rows in all, then `ANALYZE`. Both runs returned the same page, Apps 1 to 20 with snapshot ids 2201 to 2220. The plans below are cut to their nodes and row counts: costs, per-node buffers and memory lines are dropped, and the sort keys' table qualifiers shortened.

Before, at revision `8b3a1162eb95`, every App snapshot was read, sorted and ranked to produce a 21-row page:

```text
Limit (actual rows=21 loops=1)
  -> Sort (actual rows=21 loops=1)  Sort Key: score_snapshot.app_id
     -> Hash Join (actual rows=100 loops=1)
        -> Seq Scan on score_snapshot (actual rows=2320 loops=1)
        -> Hash (actual rows=100 loops=1)
           -> Subquery Scan on anon_1 (actual rows=100 loops=1)  Filter: (anon_1.rn = 1)
              -> WindowAgg (actual rows=100 loops=1)
                 -> Sort (actual rows=2300 loops=1)  Sort Key: app_id, snapshot_at DESC, id DESC
                    -> Seq Scan on score_snapshot score_snapshot_1 (actual rows=2300 loops=1)
Buffers: shared hit=58
```

After, at revision `b65e800fc49b`, 21 Apps were walked in primary key order and each was probed once:

```text
Limit (actual rows=21 loops=1)
  -> Nested Loop (actual rows=21 loops=1)
     -> Index Scan using app_pkey on app (actual rows=21 loops=1)
     -> Limit (actual rows=1 loops=21)
        -> Index Scan using ix_score_snapshot_app_id_snapshot_at_id on score_snapshot score_snapshot_1 (actual rows=1 loops=21)
           Index Cond: (app_id = app.id)
Buffers: shared hit=65
```

No node in the after plan reads the table's row count, which was the bar this record set for the change. The buffer counts are close at this volume, 58 before and 65 after, because 2,320 rows fit in 29 pages; the before plan's reads grow with the table, and the after plan's grow with the page size.

The plans above cover that one read. The Org Unit and Brand owner types of `list_latest_scores`, the rollup children read `_latest_child_snapshots` and the Brand children read `_latest_brand_app_snapshots` were not planned, so the claim that the partial unique indexes serve their probes is reasoned from the index shape rather than measured. #182's AC3 is read with `score_snapshot` as the table whose row count no node may read. The probe walks the Owner table, so a read is bounded by the Owners it scans rather than by the page size, and a filter that matches few Owners probes more Owners than the page returns.

Revisit when: a Latest Score Snapshot consumer has no Owner set to drive a probe from, or the PostgreSQL major in use can stop a `DISTINCT ON` read early.
