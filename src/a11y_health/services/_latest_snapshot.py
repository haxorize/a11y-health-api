"""The one definition of Latest Score Snapshot: newest `snapshot_at`, ties broken
by `id`, per partition. Shared by the Owner Dispatcher's rollup children reads
and its `/scores/latest` read path (`owner.py`) so the two can never select
differently (ADR 0023). See `docs/architecture.md` ("The scoring & rollup model").
"""

from collections.abc import Sequence

from sqlalchemy import CompoundSelect, Select, func, or_, select
from sqlalchemy.orm import InstrumentedAttribute

from a11y_health.models.score_snapshot import ScoreSnapshot


def select_latest_snapshots(
    snapshots: Select | CompoundSelect, partition_on: Sequence[InstrumentedAttribute]
) -> Select:
    """`snapshots` must select ScoreSnapshot rows. Multiple `partition_on` columns
    partition as a tuple — never coalesced, since owner ids come from separate
    per-table sequences and can collide across owner types. Rows NULL in every
    partition column are excluded, not lumped into one shared NULL partition."""
    sub = snapshots.subquery()
    partition_cols = [sub.c[col.key] for col in partition_on]
    row_num = (
        func.row_number()
        .over(
            partition_by=partition_cols,
            order_by=(sub.c.snapshot_at.desc(), sub.c.id.desc()),
        )
        .label("rn")
    )
    ranked = select(sub.c.id, row_num).where(or_(*(col.is_not(None) for col in partition_cols))).subquery()
    return select(ScoreSnapshot).join(ranked, ScoreSnapshot.id == ranked.c.id).where(ranked.c.rn == 1)
