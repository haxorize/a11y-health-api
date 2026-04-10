from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.app import App, Brand
from a11y_health.models.org_unit import OrgUnit
from a11y_health.models.scan_run import ScanRun, ScanRunStatus


async def make_org_unit(db: AsyncSession, *, name: str = "Test Org", parent_id: int | None = None) -> OrgUnit:
    org_unit = OrgUnit(name=name, parent_id=parent_id)
    db.add(org_unit)
    await db.flush()
    return org_unit


async def make_app(
    db: AsyncSession,
    *,
    name: str = "Test App",
    slug: str = "test-app",
    brand: Brand = Brand.HUMANA,
    org_unit_id: int,
) -> App:
    app = App(name=name, slug=slug, brand=brand, org_unit_id=org_unit_id)
    db.add(app)
    await db.flush()
    return app


async def make_scan_run(
    db: AsyncSession,
    *,
    app_id: int,
    status: ScanRunStatus = ScanRunStatus.PENDING,
    scanned_at: datetime | None = None,
) -> ScanRun:
    scan_run = ScanRun(
        app_id=app_id,
        status=status,
        scanned_at=scanned_at or datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
    )
    db.add(scan_run)
    await db.flush()
    return scan_run


async def make_app_with_org_unit(
    db: AsyncSession,
    *,
    org_name: str = "Test Org",
    app_name: str = "Test App",
    slug: str = "test-app",
    brand: Brand = Brand.HUMANA,
) -> App:
    org_unit = await make_org_unit(db, name=org_name)
    return await make_app(db, name=app_name, slug=slug, brand=brand, org_unit_id=org_unit.id)


async def make_scan_run_with_parents(
    db: AsyncSession,
    *,
    org_name: str = "Test Org",
    app_name: str = "Test App",
    slug: str = "test-app",
    brand: Brand = Brand.HUMANA,
    status: ScanRunStatus = ScanRunStatus.PENDING,
    scanned_at: datetime | None = None,
) -> ScanRun:
    app = await make_app_with_org_unit(db, org_name=org_name, app_name=app_name, slug=slug, brand=brand)
    return await make_scan_run(db, app_id=app.id, status=status, scanned_at=scanned_at)
