# Score snapshots are append-only — one new row per scoring event

Every scoring event — scan run completion, rollup recomputation — produces a
new `score_snapshot` row. Existing rows are never updated. The "current score"
for an owner (App, Org Unit, Brand) is always "the latest row by `snapshot_at`,
tiebreak on `id`" (see `c31ab92`). The rollup queries in `services/score_snapshot.py`
are built around this access pattern.

One new row per scoring event, refined (#95): one new row per **distinct
observation**. A rollup trigger whose recomputed aggregate lands on the
observation time the owner's latest snapshot already holds is not a new
observation — `_aggregate_and_save` records nothing when the values are also
identical, and replaces the rows sharing that `snapshot_at` when they differ.
Without this, every deletion/reparent trigger and every completion of an older
scan appended a row identical to the latest (same `snapshot_at`, same values),
making within-time ordering id-dependent and rendering phantom trend movement.
A strictly newer `snapshot_at` always appends, even with unchanged values — a
flat trend is still made of real observations, and skipping one would leave
the latest snapshot claiming an observation time whose source scan may later
be deleted.

Three exceptions, all delete + insert or skip (never in-place update):

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
- **Same-observation skip/replace on rollup** (#95, above): nothing recorded
  when the aggregate is identical to the latest snapshot; delete + insert of
  the rows sharing the derived `snapshot_at` when the values changed.

Those three are the complete runtime census. Beyond runtime, a one-time repair
migration may delete rows to converge history written before a rule existed —
first: `b362121027a0` (#97), removing pre-#95 duplicate rollup rows in favor of
the row the latest-selection tiebreak already serves; `8b3a1162eb95` (#98)
re-runs that dedupe before creating its indexes, so duplicates raced in between
the two deploys cannot fail enforcement.

Database-enforced since #98: partial unique indexes
(`uq_score_snapshot_org_unit_snapshot_at`, `uq_score_snapshot_brand_snapshot_at`)
make one rollup snapshot per owner and observation time impossible to violate,
not merely unviolated. The read-check dedupe above stays the primary path; the
indexes only decide same-observation write races, where the losing rollup's
transaction fails as `ConcurrentRollupError` (409, retryable) via the integrity
guard (ADR 0028). The mode lives in the `ERROR_MODES` table only — deliberately
undeclared in per-operation `error_responses(...)`, since rollups run behind
most mutating operations and a per-operation census would smear it across the
contract.
App snapshots stay unconstrained — two Scan Runs may legitimately share an
observation time, with latest selection breaking the tie on id.

Trend history for normal forward progress is preserved: each new scan
adds a rollup at a strictly newer `snapshot_at`, so the prune and the
same-observation dedupe are no-ops.

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
