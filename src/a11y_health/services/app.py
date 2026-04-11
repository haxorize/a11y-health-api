from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import DuplicateSlugError, NotFoundError
from a11y_health.models.app import UQ_APP_SLUG, App, Brand
from a11y_health.schemas.app import AppCreate, AppUpdate
from a11y_health.services.org_unit import get_org_unit

_RESOURCE = "App"


async def list_apps(
    session: AsyncSession, *, brand: Brand | None = None, offset: int = 0, limit: int = 20
) -> Sequence[App]:
    stmt = select(App)
    if brand is not None:
        stmt = stmt.where(App.brand == brand)
    result = await session.execute(stmt.order_by(App.id).offset(offset).limit(limit))
    return result.scalars().all()


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
    app = await get_app(session, app_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(app, field, value)
    await session.flush()
    await session.refresh(app)
    return app


async def delete_app(session: AsyncSession, app_id: int) -> None:
    app = await get_app(session, app_id)
    await session.delete(app)
    await session.flush()
