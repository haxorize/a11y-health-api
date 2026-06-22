"""The switchboard that decides which rollups fire after a change.

Each `on_*` handler maps a domain event (scan run completed or deleted, app
deleted or reassigned, org unit reparented) to the score computation and rollups
it must trigger. The actual computation lives in `score_snapshot.py`.

See `docs/architecture.md` ("What triggers a rollup") for the event-to-rollup table.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.scan_run import ScanRun
from a11y_health.services import app as app_service
from a11y_health.services import score_snapshot as score_snapshot_service


async def on_scan_run_completed(session: AsyncSession, scan_run: ScanRun) -> None:
    await score_snapshot_service.compute_app_score(session, scan_run)
    app = await app_service.get_app(session, scan_run.app_id)
    await score_snapshot_service.rollup_org_unit_scores(session, app.org_unit_id)
    await score_snapshot_service.rollup_brand_scores(session, app.brand_id)


async def on_scan_run_deleted(session: AsyncSession, org_unit_id: int, brand_id: int) -> None:
    await score_snapshot_service.rollup_org_unit_scores(session, org_unit_id)
    await score_snapshot_service.rollup_brand_scores(session, brand_id)


async def on_app_deleted(session: AsyncSession, org_unit_id: int, brand_id: int) -> None:
    await score_snapshot_service.rollup_org_unit_scores(session, org_unit_id)
    await score_snapshot_service.rollup_brand_scores(session, brand_id)


async def on_app_reassigned(session: AsyncSession, old_org_unit_id: int, new_org_unit_id: int) -> None:
    await score_snapshot_service.rollup_org_unit_scores(session, old_org_unit_id)
    await score_snapshot_service.rollup_org_unit_scores(session, new_org_unit_id)


async def on_org_unit_reparented(
    session: AsyncSession,
    org_unit_id: int,
    old_parent_id: int | None,
    new_parent_id: int | None,
) -> None:
    if old_parent_id is not None:
        await score_snapshot_service.rollup_org_unit_scores(session, old_parent_id)
    if new_parent_id is not None:
        await score_snapshot_service.rollup_org_unit_scores(session, new_parent_id)
