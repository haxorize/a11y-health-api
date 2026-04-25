from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.enums import ScanRunStatus
from a11y_health.models.scan_run import ScanRun
from a11y_health.models.score_snapshot import ScoreSnapshot
from a11y_health.services import app as app_service
from a11y_health.services import score as score_service


async def on_scan_run_completed(session: AsyncSession, scan_run: ScanRun) -> None:
    await score_service.compute_app_score(session, scan_run)
    app = await app_service.get_app(session, scan_run.app_id)
    await score_service.rollup_org_unit_scores(session, app.org_unit_id)
    await score_service.rollup_brand_scores(session, app.brand_id)


async def on_scan_run_deleted(session: AsyncSession, app_id: int, org_unit_id: int, brand_id: int) -> None:
    result = await session.execute(
        select(ScanRun)
        .where(ScanRun.app_id == app_id, ScanRun.status == ScanRunStatus.COMPLETED)
        .order_by(ScanRun.scanned_at.desc())
        .limit(1)
    )
    latest_run = result.scalar_one_or_none()
    if latest_run is not None:
        existing = await session.execute(select(ScoreSnapshot).where(ScoreSnapshot.scan_run_id == latest_run.id))
        old_snapshot = existing.scalar_one_or_none()
        if old_snapshot is not None:
            await session.delete(old_snapshot)
            await session.flush()
        await score_service.compute_app_score(session, latest_run)
    await score_service.rollup_org_unit_scores(session, org_unit_id)
    await score_service.rollup_brand_scores(session, brand_id)


async def on_app_deleted(session: AsyncSession, org_unit_id: int, brand_id: int) -> None:
    await score_service.rollup_org_unit_scores(session, org_unit_id)
    await score_service.rollup_brand_scores(session, brand_id)


async def on_app_reassigned(session: AsyncSession, old_org_unit_id: int, new_org_unit_id: int) -> None:
    await score_service.rollup_org_unit_scores(session, old_org_unit_id)
    await score_service.rollup_org_unit_scores(session, new_org_unit_id)


async def on_org_unit_reparented(
    session: AsyncSession,
    org_unit_id: int,
    old_parent_id: int | None,
    new_parent_id: int | None,
) -> None:
    if old_parent_id is not None:
        await score_service.rollup_org_unit_scores(session, old_parent_id)
    if new_parent_id is not None:
        await score_service.rollup_org_unit_scores(session, new_parent_id)
