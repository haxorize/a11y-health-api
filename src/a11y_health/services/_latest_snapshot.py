"""The one definition of Latest Score Snapshot: newest `snapshot_at`, ties
broken by `id`, per Owner. Shared by the Owner Dispatcher's rollup children
reads and its `/scores/latest` read path (`owner.py`) so the two can never
select differently (ADR 0023). See `docs/architecture.md` ("The scoring &
rollup model").

Each Owner is probed for its first row in that order, so a read costs one
index probe per Owner rather than a ranking of every snapshot (ADR 0051).
"""

from sqlalchemy import Select, select, true
from sqlalchemy.orm import InstrumentedAttribute, aliased

from a11y_health.models.app import App
from a11y_health.models.brand import Brand
from a11y_health.models.org_unit import OrgUnit
from a11y_health.models.score_snapshot import ScoreSnapshot


def select_latest_snapshots(
    owner: type[App] | type[OrgUnit] | type[Brand], owner_col: InstrumentedAttribute[int | None]
) -> Select:
    """Selects from `owner`'s table, so a caller narrows the Owners with
    `.where()` on its columns and can order or page on its `id`, which is
    what lets a LIMIT stop the walk. An Owner with no snapshot yields no
    row."""
    probed = aliased(ScoreSnapshot)
    latest = (
        select(probed)
        .where(getattr(probed, owner_col.key) == owner.id)
        .order_by(probed.snapshot_at.desc(), probed.id.desc())
        .limit(1)
        .subquery()
        .lateral()
    )
    return select(aliased(ScoreSnapshot, latest)).select_from(owner).join(latest, true())
