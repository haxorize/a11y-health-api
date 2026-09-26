from datetime import UTC, datetime

import pytest
from pytest import approx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import (
    EmptyScanRunError,
    InvalidStatusTransitionError,
    NotFoundError,
)
from a11y_health.models.enums import ScanRunStatus
from a11y_health.models.scan_run import ScanRun
from a11y_health.models.score_snapshot import ScoreSnapshot
from a11y_health.schemas.scan_run import ScanRunCreate, ScanRunStatusUpdate
from a11y_health.services import scan_run as scan_run_service
from a11y_health.services.page_result import create_page_result
from tests.factories import (
    app_snapshots,
    ingest_and_score,
    latest_brand_snapshot,
    latest_ou_snapshot,
    make_app,
    make_app_with_org_unit,
    make_axe_payload,
    make_brand,
    make_org_unit,
    make_scan_run,
    make_scan_run_with_parents,
    make_violation,
    recorded_statements,
    score_new_scan_run,
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


# Reds if the create path re-reads its whole row: the INSERT's RETURNING carries
# the timestamps, and the App is already in the identity map, so the one read
# after the insert is of scanned_at, which Postgres normalizes to UTC.
async def test_create_scan_run_takes_its_timestamps_from_the_insert(db_session: AsyncSession) -> None:
    app = await make_app_with_org_unit(db_session)
    async with recorded_statements(db_session) as statements:
        scan_run = await scan_run_service.create_scan_run(
            db_session, app.id, ScanRunCreate(scanned_at=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC))
        )
    returned = (scan_run.created_at, scan_run.updated_at)

    assert len(statements) == 2
    assert "created_at" not in statements[1]
    stored = await db_session.execute(select(ScanRun.created_at, ScanRun.updated_at).where(ScanRun.id == scan_run.id))
    assert returned == tuple(stored.one())


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


async def test_list_scan_runs_newest_first(db_session: AsyncSession) -> None:
    app_a = await make_app_with_org_unit(db_session, slug="app-a")
    app_b = await make_app_with_org_unit(db_session, slug="app-b")
    older = await make_scan_run(db_session, app_id=app_a.id, scanned_at=datetime(2026, 1, 1, tzinfo=UTC))
    newer = await make_scan_run(db_session, app_id=app_a.id, scanned_at=datetime(2026, 3, 1, tzinfo=UTC))
    await make_scan_run(db_session, app_id=app_b.id, scanned_at=datetime(2026, 2, 1, tzinfo=UTC))

    page = await scan_run_service.list_scan_runs(db_session, app_a.id)

    assert [r.id for r in page.items] == [newer.id, older.id]
    assert all(r.app_id == app_a.id for r in page.items)


async def test_list_scan_runs_invalid_app(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError, match="App"):
        await scan_run_service.list_scan_runs(db_session, 999999)


async def test_update_status_pending_to_completed(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    await create_page_result(db_session, scan_run.id, make_axe_payload())

    updated = await scan_run_service.update_scan_run_status(
        db_session, scan_run.id, ScanRunStatusUpdate(status=ScanRunStatus.COMPLETED)
    )
    assert updated.status == ScanRunStatus.COMPLETED


async def test_complete_empty_run_rejected(db_session: AsyncSession) -> None:
    # A Scan Run has one or more Page Results (DOMAIN.md): completing an empty
    # run would mint a 0.0 snapshot that scores "no data" as "all critical".
    scan_run = await make_scan_run_with_parents(db_session)

    with pytest.raises(EmptyScanRunError, match="no page results"):
        await scan_run_service.update_scan_run_status(
            db_session, scan_run.id, ScanRunStatusUpdate(status=ScanRunStatus.COMPLETED)
        )

    assert scan_run.status == ScanRunStatus.PENDING
    result = await db_session.execute(select(ScoreSnapshot).where(ScoreSnapshot.scan_run_id == scan_run.id))
    assert result.scalar_one_or_none() is None


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
    await create_page_result(db_session, scan_run.id, payload)

    await scan_run_service.update_scan_run_status(
        db_session, scan_run.id, ScanRunStatusUpdate(status=ScanRunStatus.COMPLETED)
    )

    [snapshot] = await app_snapshots(db_session, app.id)
    assert snapshot.score == approx(0.4)
    assert snapshot.total_pages == 1


async def test_delete_scan_run(db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)

    await scan_run_service.delete_scan_run(db_session, scan_run.id)

    with pytest.raises(NotFoundError):
        await scan_run_service.get_scan_run(db_session, scan_run.id)


# The deleted run was its App's newest, so both of that App's rollup owners
# fall back to the older run. Red when the delete rolls up another App's owners.
async def test_delete_scan_run_rolls_up_its_own_apps_owners(db_session: AsyncSession) -> None:
    brand = await make_brand(db_session)
    root = await make_org_unit(db_session, name="Root")
    org_unit = await make_org_unit(db_session, name="Owning Unit", parent_id=root.id)
    app = await make_app(db_session, slug="app-a", org_unit_id=org_unit.id, brand_id=brand.id)
    other_unit = await make_org_unit(db_session, name="Other Unit", parent_id=root.id)
    other_app = await make_app(db_session, slug="app-b", org_unit_id=other_unit.id)
    serious = make_axe_payload(violations=[make_violation("r1", "serious")])
    await score_new_scan_run(db_session, app.id, [serious], datetime(2026, 3, 1, tzinfo=UTC))
    newer = await make_scan_run(db_session, app_id=app.id, scanned_at=datetime(2026, 4, 1, tzinfo=UTC))
    await ingest_and_score(db_session, newer.id, [make_axe_payload()])
    await score_new_scan_run(db_session, other_app.id, [make_axe_payload()])

    await scan_run_service.delete_scan_run(db_session, newer.id)

    assert (await latest_ou_snapshot(db_session, org_unit.id)).score == approx(0.4)
    assert (await latest_brand_snapshot(db_session, brand.id)).score == approx(0.4)


async def test_delete_scan_run_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError, match="Scan run"):
        await scan_run_service.delete_scan_run(db_session, 999999)
