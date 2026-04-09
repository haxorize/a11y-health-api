from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.app import App, Brand
from a11y_health.models.org_unit import OrgUnit


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
