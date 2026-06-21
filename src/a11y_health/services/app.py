from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import DuplicateSlugError, NotFoundError
from a11y_health.core.pagination import CursorPage, paginate
from a11y_health.models.app import UQ_APP_SLUG, App
from a11y_health.schemas.app import AppCreate, AppUpdate
from a11y_health.services.org_unit import get_descendant_ids

_RESOURCE = "App"


async def list_apps(
    session: AsyncSession,
    *,
    brand_id: list[int] | None = None,
    org_unit_id: list[int] | None = None,
    cursor: str | None = None,
    limit: int = 20,
) -> CursorPage[App]:
    stmt = select(App)
    if brand_id:
        stmt = stmt.where(App.brand_id.in_(brand_id))
    if org_unit_id:
        expanded = await get_descendant_ids(session, org_unit_id)
        stmt = stmt.where(App.org_unit_id.in_(expanded))
    return await paginate(session, stmt, keyset=[App.id], cursor=cursor, limit=limit)


async def get_app_by_slug(session: AsyncSession, slug: str) -> App:
    result = await session.execute(select(App).where(App.slug == slug))
    app = result.scalar_one_or_none()
    if app is None:
        raise NotFoundError(_RESOURCE, slug)
    return app


async def get_app(session: AsyncSession, app_id: int) -> App:
    app = await session.get(App, app_id)
    if app is None:
        raise NotFoundError(_RESOURCE, app_id)
    return app


async def create_app(session: AsyncSession, data: AppCreate) -> App:
    from a11y_health.services.brand import get_brand
    from a11y_health.services.org_unit import get_org_unit

    await get_brand(session, data.brand_id)
    await get_org_unit(session, data.org_unit_id)
    app = App(**data.model_dump())
    session.add(app)
    try:
        async with session.begin_nested():
            await session.flush()
    except IntegrityError as exc:
        if UQ_APP_SLUG in str(exc):
            raise DuplicateSlugError(data.slug) from exc
        raise
    await session.refresh(app)
    return app


async def update_app(session: AsyncSession, app_id: int, data: AppUpdate) -> App:
    from a11y_health.services import scoring_orchestration

    app = await get_app(session, app_id)
    fields = data.model_dump(exclude_unset=True)
    old_org_unit_id = app.org_unit_id
    new_org_unit_id = fields.get("org_unit_id")
    reassigning = new_org_unit_id is not None and new_org_unit_id != old_org_unit_id

    if new_org_unit_id is not None:
        from a11y_health.services.org_unit import get_org_unit

        await get_org_unit(session, new_org_unit_id)

    for field, value in fields.items():
        setattr(app, field, value)
    await session.flush()
    await session.refresh(app)

    if reassigning:
        await scoring_orchestration.on_app_reassigned(session, old_org_unit_id, new_org_unit_id)

    return app


async def delete_app(session: AsyncSession, app_id: int) -> None:
    from a11y_health.services import scoring_orchestration

    app = await get_app(session, app_id)
    org_unit_id = app.org_unit_id
    brand_id = app.brand_id
    await session.delete(app)
    await session.flush()
    await scoring_orchestration.on_app_deleted(session, org_unit_id, brand_id)
