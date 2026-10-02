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
    new_org_unit_id = data.org_unit_id
    stmt = select(App).where(App.id == app_id)
    if new_org_unit_id is not None:
        # The lock the UPDATE takes anyway, taken at the load, so a concurrent
        # move or delete is waited out and the old unit is read after it (ADR
        # 0048). populate_existing, so an App this session loaded earlier
        # does not keep the unit it read then.
        stmt = stmt.with_for_update(key_share=True).execution_options(populate_existing=True)
    app = await existence.get_by_query(session, App, stmt, app_id)
    old_org_unit_id = app.org_unit_id
    reassigning = new_org_unit_id is not None and new_org_unit_id != old_org_unit_id

    if new_org_unit_id is not None:
        org_unit_reference = await existence.require_reference(session, OrgUnit, new_org_unit_id, FK_APP_ORG_UNIT_ID)
        async with integrity.guard_constraints(session, org_unit_reference):
            app.org_unit_id = new_org_unit_id
        # Only after a write: with none, the row was read unlocked, and a
        # refresh would fail unmapped on one deleted since (ADR 0048).
        await session.refresh(app)

    if reassigning:
        await scoring_orchestration.on_app_reassigned(session, old_org_unit_id, new_org_unit_id)

    return app


async def _lock_app_for_delete(session: AsyncSession, app_id: int) -> App:
    # KEY SHARE on the unit, the lock the rollup's Org Unit Score Snapshot
    # insert takes on it later, then the App itself: the order Org Unit
    # deletion locks them in (ADR 0048). The unit lock blocks only that
    # deletion, so App deletions and renames in the unit still run together.
    unit_locked = (
        select(App.org_unit_id)
        .join(OrgUnit, OrgUnit.id == App.org_unit_id)
        .where(App.id == app_id)
        .with_for_update(read=True, key_share=True, of=OrgUnit)
    )
    while True:
        org_unit_id = (await session.execute(unit_locked)).scalar_one_or_none()
        if org_unit_id is None:
            # The App is gone, or the unit it was in was deleted during the
            # wait after it moved out; the next pass locks the unit it is in.
            await existence.get_by_query(session, App, select(App).where(App.id == app_id), app_id)
            continue
        # populate_existing, so an App this session loaded earlier names the
        # unit locked here, which is the one the rollup reads.
        app_locked = (
            select(App)
            .where(App.id == app_id, App.org_unit_id == org_unit_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (app := (await session.execute(app_locked)).scalar_one_or_none()) is not None:
            return app
        # Moved or deleted while this waited: the next pass reads which.


async def delete_app(session: AsyncSession, app_id: int) -> None:
    app = await _lock_app_for_delete(session, app_id)
    await session.delete(app)
    await session.flush()
    await scoring_orchestration.on_app_latest_snapshot_changed(session, app)
