# Score snapshots are append-only — one new row per scoring event

Every scoring event — scan run completion, rollup recomputation — produces a
new `score_snapshot` row. Existing rows are never updated. The "current score"
for an owner (App, Org Unit, Brand) is always "the latest row by `snapshot_at`,
tiebreak on `id`" (see `c31ab92`). The rollup queries in `services/score.py`
are built around this access pattern.

The one exception is rebuild on cascade: when a scan run is deleted,
`on_scan_run_deleted` deletes the orphaned snapshot and recomputes the App's
latest from the next-newest run, then triggers the rollup. That's a delete +
insert, not an in-place update.

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
