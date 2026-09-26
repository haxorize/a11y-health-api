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
    await on_app_latest_snapshot_changed(session, app_rollup_targets(app))


# Resource services may not import the Owner Dispatcher
# (tests/test_sibling_imports.py), so the capture a deleting caller makes before
# its delete comes through here.
def app_rollup_targets(app: App) -> tuple[owner.RollupTarget, ...]:
    return owner.app_rollup_targets(app)


# The shared tail of completion and both deletions (a scan run, the whole app):
# whichever way the app's latest Score Snapshot moved, every rollup target
# fires, in the order the Owner Dispatcher hands them over. A caller deleting
# the app captures the targets first.
async def on_app_latest_snapshot_changed(session: AsyncSession, targets: tuple[owner.RollupTarget, ...]) -> None:
    for target in targets:
        await owner.rollup(session, target.owner_type, target.owner_id)


async def on_app_reassigned(session: AsyncSession, old_org_unit_id: int, new_org_unit_id: int) -> None:
    await owner.rollup(session, ScoreSnapshotOwnerType.ORG_UNIT, old_org_unit_id)
    await owner.rollup(session, ScoreSnapshotOwnerType.ORG_UNIT, new_org_unit_id)


async def on_org_unit_reparented(
    session: AsyncSession,
    *,
    old_parent_id: int | None,
    new_parent_id: int | None,
) -> None:
    if old_parent_id is not None:
        await owner.rollup(session, ScoreSnapshotOwnerType.ORG_UNIT, old_parent_id)
    if new_parent_id is not None:
        await owner.rollup(session, ScoreSnapshotOwnerType.ORG_UNIT, new_parent_id)
