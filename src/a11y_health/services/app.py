from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core import existence, integrity
from a11y_health.core.exceptions import DuplicateSlugError
from a11y_health.core.pagination import DEFAULT_PAGE_SIZE, CursorPage, paginate
from a11y_health.core.slug import derive_slug
from a11y_health.models.app import UQ_APP_SLUG, App
from a11y_health.models.brand import Brand
from a11y_health.models.org_unit import OrgUnit
from a11y_health.schemas.app import AppCreate, AppUpdate
from a11y_health.services import scoring_orchestration
from a11y_health.services._org_subtree import select_descendant_ids


async def list_apps(
    session: AsyncSession,
    *,
    brand_id: list[int] | None = None,
    org_unit_id: list[int] | None = None,
    direct_only: bool = False,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> CursorPage[App]:
    stmt = select(App)
    if brand_id:
        stmt = stmt.where(App.brand_id.in_(brand_id))
    if org_unit_id:
        # The /scores/latest opt-in (ADR 0035); no filter, nothing to refine.
        unit_ids = org_unit_id if direct_only else select_descendant_ids(org_unit_id)
        stmt = stmt.where(App.org_unit_id.in_(unit_ids))
    return await paginate(session, stmt, keyset=[App.id], cursor=cursor, limit=limit)


async def get_app_by_slug(session: AsyncSession, slug: str) -> App:
    return await existence.get_by_query(session, App, select(App).where(App.slug == slug), slug)


async def get_app(session: AsyncSession, app_id: int) -> App:
    return await existence.get_by_pk(session, App, app_id)


async def create_app(session: AsyncSession, data: AppCreate) -> App:
    await existence.get_by_pk(session, Brand, data.brand_id)
    await existence.get_by_pk(session, OrgUnit, data.org_unit_id)
    slug = derive_slug(data.name)
    app = App(**data.model_dump(), slug=slug)
    async with integrity.guard(session, {UQ_APP_SLUG: DuplicateSlugError(slug)}):
        session.add(app)
    await session.refresh(app)
    return app


async def update_app(session: AsyncSession, app_id: int, data: AppUpdate) -> App:
    app = await get_app(session, app_id)
    old_org_unit_id = app.org_unit_id
    new_org_unit_id = data.org_unit_id
    reassigning = new_org_unit_id is not None and new_org_unit_id != old_org_unit_id

    if new_org_unit_id is not None:
        await existence.get_by_pk(session, OrgUnit, new_org_unit_id)
        app.org_unit_id = new_org_unit_id

    await session.flush()
    await session.refresh(app)

    if reassigning:
        await scoring_orchestration.on_app_reassigned(session, old_org_unit_id, new_org_unit_id)

    return app


async def delete_app(session: AsyncSession, app_id: int) -> None:
    app = await get_app(session, app_id)
    org_unit_id = app.org_unit_id
    brand_id = app.brand_id
    await session.delete(app)
    await session.flush()
    await scoring_orchestration.on_app_latest_snapshot_changed(session, org_unit_id, brand_id)
