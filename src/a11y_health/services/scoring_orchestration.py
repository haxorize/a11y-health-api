from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.scan_run import ScanRun
from a11y_health.services import app as app_service
from a11y_health.services import score as score_service


async def on_scan_run_completed(session: AsyncSession, scan_run: ScanRun) -> None:
    snapshot = await score_service.compute_app_score(session, scan_run)
    app = await app_service.get_app(session, scan_run.app_id)
    await score_service.rollup_org_unit_scores(session, app.org_unit_id, snapshot.snapshot_at)
    await score_service.rollup_brand_scores(session, app.brand_id, snapshot.snapshot_at)


async def on_org_unit_reparented(
    session: AsyncSession,
    org_unit_id: int,
    old_parent_id: int | None,
    new_parent_id: int | None,
) -> None:
    now = datetime.now(UTC)
    if old_parent_id is not None:
        await score_service.rollup_org_unit_scores(session, old_parent_id, now)
    if new_parent_id is not None:
        await score_service.rollup_org_unit_scores(session, new_parent_id, now)
