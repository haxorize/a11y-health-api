# Score snapshots are append-only — one new row per scoring event

Every scoring event — scan run completion, rollup recomputation — produces a
new `score_snapshot` row. Existing rows are never updated. The "current score"
for an owner (App, Org Unit, Brand) is always "the latest row by `snapshot_at`,
tiebreak on `id`" (see `c31ab92`). The rollup queries in `services/score_snapshot.py`
are built around this access pattern.

Two exceptions, both delete + insert (never in-place update):

- **Cascade on scan-run delete**: the App snapshot for a deleted scan run is
  removed by the database FK cascade (`scan_run_id` carries
  `ondelete="CASCADE"`), not by the handler — `on_scan_run_deleted` only
  re-triggers the rollups, which aggregate from whatever snapshot is now the
  App's latest.
- **Forward-stale prune on rollup**: `_aggregate_and_save` derives
  `snapshot_at = max(child.snapshot_at)` and deletes any snapshots for the
  same owner whose `snapshot_at` is strictly past that max. When source data
  shrinks (deletion, reassignment, reparenting), prior rollup rows stamped at
  later observation times are orphaned claims — the data behind them is
  gone — and would otherwise win `order by snapshot_at desc` queries against
  a derived score that no source can reproduce.

Trend history for normal forward progress is preserved: each new scan
adds a rollup at a strictly newer `snapshot_at`, so the prune is a no-op.

Considered and rejected:
- **Upsert one row per (owner, owner_id)**: simpler storage, but loses score
  trend history for free. The trend endpoints (#10) and any future audit-of-
  scoring requirement would need parallel storage. Append-only is cheap on
  PG (one BIGINT PK + indexed lookup) and gets trend for free.
- **Append-only with a `current` flag**: would require flipping the flag on
  every new snapshot under a transaction, recreating the upsert hazard
  inside an append-only model. The latest-by-timestamp-then-id query is
  simpler and stable.

If snapshot volume becomes a real cost, the answer is partition pruning or
retention, not making them mutable.
