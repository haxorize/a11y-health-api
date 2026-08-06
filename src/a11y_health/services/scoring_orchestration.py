"""The switchboard that decides which rollups fire after a change.

Each `on_*` handler maps a domain event (scan run completed or deleted, app
deleted or reassigned, org unit reparented) to the score computation and rollups
it must trigger. App-score computation lives in `score_snapshot.py`; the rollups
in `owner.py` (the Owner Dispatcher).

See `docs/architecture.md` ("What triggers a rollup") for the event-to-rollup
table.

Operations calling in here must declare the retryable `concurrent_rollup` mode —
enforced structurally by the instrumentation in `tests/_declaration_honesty.py`.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core import existence
from a11y_health.models.app import App
from a11y_health.models.enums import ScoreSnapshotOwnerType
from a11y_health.models.scan_run import ScanRun
from a11y_health.services import owner
from a11y_health.services import score_snapshot as score_snapshot_service


async def on_scan_run_completed(session: AsyncSession, scan_run: ScanRun) -> None:
    await score_snapshot_service.compute_app_score(session, scan_run)
    app = await existence.get_by_pk(session, App, scan_run.app_id)
    await on_app_latest_snapshot_changed(session, app.org_unit_id, app.brand_id)


# The one deletion handler: a scan run's or the whole app's snapshots are gone,
# and the app's latest Score Snapshot may have moved — same rollup pair either
# way.
async def on_app_latest_snapshot_changed(session: AsyncSession, org_unit_id: int, brand_id: int) -> None:
    await owner.rollup(session, ScoreSnapshotOwnerType.ORG_UNIT, org_unit_id)
    await owner.rollup(session, ScoreSnapshotOwnerType.BRAND, brand_id)


async def on_app_reassigned(session: AsyncSession, old_org_unit_id: int, new_org_unit_id: int) -> None:
    await owner.rollup(session, ScoreSnapshotOwnerType.ORG_UNIT, old_org_unit_id)
    await owner.rollup(session, ScoreSnapshotOwnerType.ORG_UNIT, new_org_unit_id)


async def on_org_unit_reparented(
    session: AsyncSession,
    org_unit_id: int,
    old_parent_id: int | None,
    new_parent_id: int | None,
) -> None:
    if old_parent_id is not None:
        await owner.rollup(session, ScoreSnapshotOwnerType.ORG_UNIT, old_parent_id)
    if new_parent_id is not None:
        await owner.rollup(session, ScoreSnapshotOwnerType.ORG_UNIT, new_parent_id)
