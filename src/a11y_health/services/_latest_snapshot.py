"""The one definition of Latest Score Snapshot: newest `snapshot_at`, ties
broken by `id`, per Owner. Shared by the Owner Dispatcher's rollup children
reads and its `/scores/latest` read path (`owner.py`) so the two can never
select differently (ADR 0023). See `docs/architecture.md` ("The scoring &
rollup model").

Each Owner is probed for its first row in that order, so a read costs one
index probe per Owner rather than a ranking of every snapshot (ADR 0051).
"""

from typing import Protocol

from sqlalchemy import Select, select, true
from sqlalchemy.orm import InstrumentedAttribute, aliased

from a11y_health.core.database import Base
from a11y_health.models.score_snapshot import ScoreSnapshot


# Satisfied by the Owner Dispatcher's `OwnerSpec`, which this module cannot
# import without a cycle; taking the pair whole keeps an Owner's table and its
# snapshot column from being mismatched.
class ProbedOwner(Protocol):
    @property
    def entity(self) -> type[Base]: ...
    @property
    def id_column(self) -> InstrumentedAttribute[int | None]: ...


def select_latest_snapshots(owner: ProbedOwner) -> Select:
    """Selects from the Owner's table, so a caller narrows the Owners with
    `.where()` on its columns and can order on its `id`, which is what lets a
    LIMIT stop the walk. An Owner with no snapshot yields no row.

    The selected snapshot is an alias, not `ScoreSnapshot`: a `.where()` on a
    `ScoreSnapshot` column adds a second, unjoined `score_snapshot`. Paging
    with `paginate` on the Owner's `id` needs `.add_columns(owner.entity)`
    first, since only the snapshot is selected."""
    latest = (
        select(ScoreSnapshot)
        .where(owner.id_column == owner.entity.id)
        .order_by(ScoreSnapshot.snapshot_at.desc(), ScoreSnapshot.id.desc())
        .limit(1)
        # Never `score_snapshot`, even when a caller's filter puts it in the
        # outer FROM.
        .correlate(owner.entity)
        .subquery()
        .lateral()
    )
    return select(aliased(ScoreSnapshot, latest)).select_from(owner.entity).join(latest, true())
