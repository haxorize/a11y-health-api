from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core import existence, integrity
from a11y_health.core.exceptions import DuplicateSlugError
from a11y_health.core.pagination import DEFAULT_PAGE_SIZE, CursorPage, paginate
from a11y_health.core.slug import derive_slug
from a11y_health.models.app import FK_APP_ORG_UNIT_ID, UQ_APP_SLUG, App
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
        # With several units, direct_only serves each listed unit's own apps.
        unit_scope = org_unit_id if direct_only else select_descendant_ids(org_unit_id)
        stmt = stmt.where(App.org_unit_id.in_(unit_scope))
    return await paginate(session, stmt, keyset=[App.id], cursor=cursor, limit=limit)


async def get_app_by_slug(session: AsyncSession, slug: str) -> App:
    return await existence.get_by_query(session, App, select(App).where(App.slug == slug), slug)


async def get_app(session: AsyncSession, app_id: int) -> App:
    return await existence.get_by_pk(session, App, app_id)


async def create_app(session: AsyncSession, data: AppCreate) -> App:
    await existence.get_by_pk(session, Brand, data.brand_id)
    org_unit_reference = await existence.require_reference(session, OrgUnit, data.org_unit_id, FK_APP_ORG_UNIT_ID)
    slug = derive_slug(data.name)
    app = App(**data.model_dump(), slug=slug)
    # The Org Unit can be deleted after its check above, and its foreign key
    # decides that race (ADR 0048). The Brand's key is unmapped because no
    # operation deletes a Brand.
    async with integrity.guard_constraints(
        session,
        {UQ_APP_SLUG: DuplicateSlugError(slug), **org_unit_reference},
    ):
        session.add(app)
    return app


async def update_app(session: AsyncSession, app_id: int, data: AppUpdate) -> App:
    app = await get_app(session, app_id)
    old_org_unit_id = app.org_unit_id
    new_org_unit_id = data.org_unit_id
    reassigning = new_org_unit_id is not None and new_org_unit_id != old_org_unit_id

    if new_org_unit_id is not None:
        org_unit_reference = await existence.require_reference(session, OrgUnit, new_org_unit_id, FK_APP_ORG_UNIT_ID)
        async with integrity.guard_constraints(session, org_unit_reference):
            app.org_unit_id = new_org_unit_id

    await session.refresh(app)

    if reassigning:
        await scoring_orchestration.on_app_reassigned(session, old_org_unit_id, new_org_unit_id)

    return app


async def delete_app(session: AsyncSession, app_id: int) -> None:
    # KEY SHARE is what the rollup's Org Unit Score Snapshot insert takes on
    # the unit later; taking it before the delete puts the Org Unit ahead of
    # the App, the order Org Unit deletion locks them in (ADR 0048).
    # populate_existing, so an App this session loaded earlier names the unit
    # locked here, which is the one the rollup reads.
    locked = (
        select(App)
        .join(OrgUnit, OrgUnit.id == App.org_unit_id)
        .where(App.id == app_id)
        .with_for_update(key_share=True, of=OrgUnit)
        .execution_options(populate_existing=True)
    )
    while (app := (await session.execute(locked)).scalar_one_or_none()) is None:
        # A miss while the App exists means the unit it was in was deleted
        # during the wait, after the App moved out; the next pass locks the
        # unit it is in now.
        await existence.get_by_query(session, App, select(App).where(App.id == app_id), app_id)
    await session.delete(app)
    await session.flush()
    await scoring_orchestration.on_app_latest_snapshot_changed(session, app)
