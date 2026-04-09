from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import (
    InvalidStatusTransitionError,
    NotFoundError,
    ScanRunCompletedError,
)
from a11y_health.models.scan_run import ScanRunStatus
from a11y_health.schemas.scan_run import ScanRunCreate, ScanRunStatusUpdate
from a11y_health.services import scan_run as scan_run_service
from tests.factories import make_app, make_org_unit, make_scan_run


async def test_create_scan_run(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    app = await make_app(db_session, org_unit_id=org_unit.id)
    scanned_at = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)

    scan_run = await scan_run_service.create_scan_run(db_session, app.id, ScanRunCreate(scanned_at=scanned_at))

    assert scan_run.id is not None
    assert scan_run.app_id == app.id
    assert scan_run.status == ScanRunStatus.PENDING
    assert scan_run.scanned_at == scanned_at
    assert scan_run.created_at is not None


async def test_create_scan_run_invalid_app(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError, match="App"):
        await scan_run_service.create_scan_run(
            db_session, 999999, ScanRunCreate(scanned_at=datetime(2026, 4, 1, tzinfo=UTC))
        )


async def test_get_scan_run(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    app = await make_app(db_session, org_unit_id=org_unit.id)
    created = await make_scan_run(db_session, app_id=app.id)

    fetched = await scan_run_service.get_scan_run(db_session, created.id)
    assert fetched.id == created.id
    assert fetched.app_id == app.id


async def test_get_scan_run_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError, match="Scan run"):
        await scan_run_service.get_scan_run(db_session, 999999)


async def test_list_scan_runs(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    app_a = await make_app(db_session, slug="app-a", org_unit_id=org_unit.id)
    app_b = await make_app(db_session, slug="app-b", org_unit_id=org_unit.id)
    await make_scan_run(db_session, app_id=app_a.id)
    await make_scan_run(db_session, app_id=app_a.id)
    await make_scan_run(db_session, app_id=app_b.id)

    result = await scan_run_service.list_scan_runs(db_session, app_a.id)
    assert len(result) == 2
    assert all(r.app_id == app_a.id for r in result)


async def test_list_scan_runs_pagination(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    app = await make_app(db_session, org_unit_id=org_unit.id)
    for _ in range(5):
        await make_scan_run(db_session, app_id=app.id)

    result = await scan_run_service.list_scan_runs(db_session, app.id, offset=1, limit=2)
    assert len(result) == 2


async def test_update_status_pending_to_completed(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    app = await make_app(db_session, org_unit_id=org_unit.id)
    scan_run = await make_scan_run(db_session, app_id=app.id)

    updated = await scan_run_service.update_scan_run_status(
        db_session, scan_run.id, ScanRunStatusUpdate(status=ScanRunStatus.COMPLETED)
    )
    assert updated.status == ScanRunStatus.COMPLETED


async def test_update_status_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError, match="Scan run"):
        await scan_run_service.update_scan_run_status(
            db_session, 999999, ScanRunStatusUpdate(status=ScanRunStatus.COMPLETED)
        )


async def test_update_status_completed_to_pending_rejected(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    app = await make_app(db_session, org_unit_id=org_unit.id)
    scan_run = await make_scan_run(db_session, app_id=app.id, status=ScanRunStatus.COMPLETED)

    with pytest.raises(InvalidStatusTransitionError, match="pending"):
        await scan_run_service.update_scan_run_status(
            db_session, scan_run.id, ScanRunStatusUpdate(status=ScanRunStatus.PENDING)
        )


async def test_update_status_completed_to_completed_rejected(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    app = await make_app(db_session, org_unit_id=org_unit.id)
    scan_run = await make_scan_run(db_session, app_id=app.id, status=ScanRunStatus.COMPLETED)

    with pytest.raises(InvalidStatusTransitionError, match="completed"):
        await scan_run_service.update_scan_run_status(
            db_session, scan_run.id, ScanRunStatusUpdate(status=ScanRunStatus.COMPLETED)
        )


async def test_completed_run_rejects_page_addition(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    app = await make_app(db_session, org_unit_id=org_unit.id)
    scan_run = await make_scan_run(db_session, app_id=app.id, status=ScanRunStatus.COMPLETED)

    with pytest.raises(ScanRunCompletedError, match="completed"):
        scan_run_service.assert_scan_run_pending(scan_run)
