from datetime import UTC, datetime

import pytest
from pytest import approx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import (
    InvalidStatusTransitionError,
    NotFoundError,
    ScanRunCompletedError,
)
from a11y_health.models.enums import ScanRunStatus
from a11y_health.models.score_snapshot import ScoreSnapshot
from a11y_health.schemas.axe_payload import AxePayload
from a11y_health.schemas.scan_run import ScanRunCreate, ScanRunStatusUpdate
from a11y_health.services import scan_run as scan_run_service
from a11y_health.services.page_result import create_page_result
from tests.factories import (
    make_app,
    make_app_with_org_unit,
    make_axe_payload,
    make_org_unit,
    make_scan_run,
    make_scan_run_with_parents,
    make_violation,
)


async def test_create_scan_run(db_session: AsyncSession) -> None:
    app = await make_app_with_org_unit(db_session)
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
    created = await make_scan_run_with_parents(db_session)

    fetched = await scan_run_service.get_scan_run(db_session, created.id)
    assert fetched.id == created.id
    assert fetched.app_id == created.app_id


async def test_get_scan_run_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError, match="Scan run"):
        await scan_run_service.get_scan_run(db_session, 999999)


async def test_list_scan_runs(db_session: AsyncSession) -> None:
    app_a = await make_app_with_org_unit(db_session, slug="app-a")
    app_b = await make_app_with_org_unit(db_session, slug="app-b")
    await make_scan_run(db_session, app_id=app_a.id)
    await make_scan_run(db_session, app_id=app_a.id)
    await make_scan_run(db_session, app_id=app_b.id)

    page = await scan_run_service.list_scan_runs(db_session, app_a.id)
    assert len(page.items) == 2
    assert all(r.app_id == app_a.id for r in page.items)


async def test_list_scan_runs_pagination(db_session: AsyncSession) -> None:
    app = await make_app_with_org_unit(db_session)
    for _ in range(5):
        await make_scan_run(db_session, app_id=app.id)

    first = await scan_run_service.list_scan_runs(db_session, app.id, limit=2)
    assert len(first.items) == 2
    assert first.next_cursor is not None
    second = await scan_run_service.list_scan_runs(db_session, app.id, cursor=first.next_cursor, limit=2)
    assert len(second.items) == 2
    assert {r.id for r in first.items}.isdisjoint({r.id for r in second.items})


async def test_update_status_pending_to_completed(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)

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
    scan_run = await make_scan_run_with_parents(db_session, status=ScanRunStatus.COMPLETED)

    with pytest.raises(InvalidStatusTransitionError, match="pending"):
        await scan_run_service.update_scan_run_status(
            db_session, scan_run.id, ScanRunStatusUpdate(status=ScanRunStatus.PENDING)
        )


async def test_update_status_completed_to_completed_rejected(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session, status=ScanRunStatus.COMPLETED)

    with pytest.raises(InvalidStatusTransitionError, match="completed"):
        await scan_run_service.update_scan_run_status(
            db_session, scan_run.id, ScanRunStatusUpdate(status=ScanRunStatus.COMPLETED)
        )


async def test_completed_transition_triggers_scoring(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session, name="Org")
    app = await make_app(db_session, name="App", slug="app-score", org_unit_id=org_unit.id)
    scan_run = await make_scan_run(db_session, app_id=app.id)

    payload = make_axe_payload(violations=[make_violation("r1", "serious")])
    await create_page_result(db_session, scan_run.id, AxePayload.model_validate(payload), payload)

    await scan_run_service.update_scan_run_status(
        db_session, scan_run.id, ScanRunStatusUpdate(status=ScanRunStatus.COMPLETED)
    )

    result = await db_session.execute(select(ScoreSnapshot).where(ScoreSnapshot.app_id == app.id))
    snapshot = result.scalar_one()
    assert snapshot.score == approx(0.4)
    assert snapshot.total_pages == 1


async def test_delete_scan_run(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)

    await scan_run_service.delete_scan_run(db_session, scan_run.id)

    with pytest.raises(NotFoundError):
        await scan_run_service.get_scan_run(db_session, scan_run.id)


async def test_delete_scan_run_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError, match="Scan run"):
        await scan_run_service.delete_scan_run(db_session, 999999)


async def test_completed_run_rejects_page_addition(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session, status=ScanRunStatus.COMPLETED)

    with pytest.raises(ScanRunCompletedError, match="completed"):
        scan_run_service.assert_scan_run_pending(scan_run)
