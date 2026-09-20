import re

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import DuplicateSlugError, NotFoundError
from a11y_health.models.scan_run import ScanRun
from a11y_health.models.score_snapshot import ScoreSnapshot
from a11y_health.schemas.app import AppCreate, AppUpdate
from a11y_health.services import app as app_service
from tests.factories import (
    make_app,
    make_app_with_org_unit,
    make_brand,
    make_org_unit,
    make_scan_run,
    make_score_snapshot,
)


async def test_create_app_derives_slug_from_name(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session, name="Humana")
    app = await app_service.create_app(
        db_session, AppCreate(name="My App (Prod)", brand_id=brand.id, org_unit_id=org_unit.id)
    )
    assert app.name == "My App (Prod)"
    assert app.slug == "my-app-prod"
    assert app.brand_id == brand.id
    assert app.org_unit_id == org_unit.id
    assert app.id is not None


async def test_create_app_invalid_brand(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    with pytest.raises(NotFoundError, match="Brand"):
        await app_service.create_app(db_session, AppCreate(name="MyApp", brand_id=999999, org_unit_id=org_unit.id))


async def test_create_app_invalid_org_unit(db_session: AsyncSession) -> None:
    brand = await make_brand(db_session)
    with pytest.raises(NotFoundError, match="Org unit"):
        await app_service.create_app(db_session, AppCreate(name="MyApp", brand_id=brand.id, org_unit_id=999999))


async def test_create_app_distinct_names_colliding_slug_conflict(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)
    await app_service.create_app(
        db_session, AppCreate(name="My App (Prod)", brand_id=brand.id, org_unit_id=org_unit.id)
    )
    with pytest.raises(DuplicateSlugError, match="my-app-prod"):
        await app_service.create_app(
            db_session, AppCreate(name="my app PROD!", brand_id=brand.id, org_unit_id=org_unit.id)
        )


async def test_get_app(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)
    created = await make_app(db_session, brand_id=brand.id, org_unit_id=org_unit.id)
    fetched = await app_service.get_app(db_session, created.id)
    assert fetched.id == created.id
    assert fetched.name == created.name


async def test_get_app_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError, match="App"):
        await app_service.get_app(db_session, 999999)


async def test_get_app_by_slug(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)
    created = await make_app(db_session, slug="find-me", brand_id=brand.id, org_unit_id=org_unit.id)
    fetched = await app_service.get_app_by_slug(db_session, "find-me")
    assert fetched.id == created.id


async def test_get_app_by_slug_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError, match="App"):
        await app_service.get_app_by_slug(db_session, "nonexistent")


async def test_list_apps(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)
    await make_app(db_session, name="App A", slug="app-a", brand_id=brand.id, org_unit_id=org_unit.id)
    await make_app(db_session, name="App B", slug="app-b", brand_id=brand.id, org_unit_id=org_unit.id)
    page = await app_service.list_apps(db_session)
    assert len(page.items) == 2
    assert page.next_cursor is None


async def test_list_apps_filter_by_brand_id(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    humana = await make_brand(db_session, name="Humana")
    go365 = await make_brand(db_session, name="Go365")
    await make_app(db_session, slug="humana-app", brand_id=humana.id, org_unit_id=org_unit.id)
    await make_app(db_session, slug="go365-app", brand_id=go365.id, org_unit_id=org_unit.id)
    page = await app_service.list_apps(db_session, brand_id=[go365.id])
    assert len(page.items) == 1
    assert page.items[0].brand_id == go365.id


async def test_list_apps_filter_by_multiple_brand_ids(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    humana = await make_brand(db_session, name="Humana")
    go365 = await make_brand(db_session, name="Go365")
    centerwell = await make_brand(db_session, name="CenterWell")
    await make_app(db_session, slug="humana-app", brand_id=humana.id, org_unit_id=org_unit.id)
    await make_app(db_session, slug="go365-app", brand_id=go365.id, org_unit_id=org_unit.id)
    await make_app(db_session, slug="centerwell-app", brand_id=centerwell.id, org_unit_id=org_unit.id)
    page = await app_service.list_apps(db_session, brand_id=[humana.id, go365.id])
    assert len(page.items) == 2
    brand_ids = {a.brand_id for a in page.items}
    assert brand_ids == {humana.id, go365.id}


async def test_list_apps_filter_by_org_unit_id_with_descendants(db_session: AsyncSession) -> None:
    top = await make_org_unit(db_session, name="Top")
    root = await make_org_unit(db_session, name="Humana", parent_id=top.id)
    child = await make_org_unit(db_session, name="CenterWell", parent_id=root.id)
    grandchild = await make_org_unit(db_session, name="Primary Care", parent_id=child.id)
    other = await make_org_unit(db_session, name="Other", parent_id=top.id)
    brand = await make_brand(db_session)
    await make_app(db_session, slug="root-app", brand_id=brand.id, org_unit_id=root.id)
    await make_app(db_session, slug="child-app", brand_id=brand.id, org_unit_id=child.id)
    await make_app(db_session, slug="grandchild-app", brand_id=brand.id, org_unit_id=grandchild.id)
    await make_app(db_session, slug="other-app", brand_id=brand.id, org_unit_id=other.id)
    page = await app_service.list_apps(db_session, org_unit_id=[root.id])
    assert len(page.items) == 3
    slugs = {a.slug for a in page.items}
    assert slugs == {"root-app", "child-app", "grandchild-app"}


# Reds if direct_only stops gating the descendant expansion.
async def test_list_apps_direct_only_serves_apps_placed_on_the_unit_itself(db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    child = await make_org_unit(db_session, name="CenterWell", parent_id=root.id)
    grandchild = await make_org_unit(db_session, name="Primary Care", parent_id=child.id)
    await make_app(db_session, slug="root-app", org_unit_id=root.id)
    await make_app(db_session, slug="child-app", org_unit_id=child.id)
    await make_app(db_session, slug="grandchild-app", org_unit_id=grandchild.id)
    page = await app_service.list_apps(db_session, org_unit_id=[root.id], direct_only=True)
    assert [a.slug for a in page.items] == ["root-app"]


# Reds if direct_only collapses a multi-unit filter to one unit (#139):
# each listed unit's own apps, none of their descendants'.
async def test_list_apps_direct_only_with_several_units_serves_each_units_own_apps(db_session: AsyncSession) -> None:
    top = await make_org_unit(db_session, name="Top")
    branch_a = await make_org_unit(db_session, name="CenterWell", parent_id=top.id)
    branch_b = await make_org_unit(db_session, name="Pharmacy", parent_id=top.id)
    under_b = await make_org_unit(db_session, name="Retail", parent_id=branch_b.id)
    await make_app(db_session, slug="a-app", org_unit_id=branch_a.id)
    await make_app(db_session, slug="b-app", org_unit_id=branch_b.id)
    await make_app(db_session, slug="under-b-app", org_unit_id=under_b.id)
    page = await app_service.list_apps(db_session, org_unit_id=[branch_a.id, branch_b.id], direct_only=True)
    assert {a.slug for a in page.items} == {"a-app", "b-app"}


async def test_list_apps_direct_only_without_org_unit_id_is_ignored(db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    leaf = await make_org_unit(db_session, name="CenterWell", parent_id=root.id)
    await make_app(db_session, slug="root-app", org_unit_id=root.id)
    await make_app(db_session, slug="leaf-app", org_unit_id=leaf.id)
    page = await app_service.list_apps(db_session, direct_only=True)
    assert {a.slug for a in page.items} == {"root-app", "leaf-app"}


# Reds if the subtree expansion round-trips again, or is lost: the recursive
# CTE rides inside every statement that reads apps, and no statement reads
# org units on its own. A count query beside the page statement stays green.
async def test_list_apps_org_unit_filter_embeds_the_subtree_expansion(db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    child = await make_org_unit(db_session, name="CenterWell", parent_id=root.id)
    await make_app(db_session, slug="child-app", org_unit_id=child.id)
    await db_session.flush()
    statements: list[str] = []
    connection = (await db_session.connection()).sync_connection
    assert connection is not None

    def record(_conn: object, _cursor: object, statement: str, *_: object) -> None:
        statements.append(statement)

    event.listen(connection, "before_cursor_execute", record)
    try:
        page = await app_service.list_apps(db_session, org_unit_id=[root.id])
    finally:
        event.remove(connection, "before_cursor_execute", record)

    assert [a.slug for a in page.items] == ["child-app"]
    reading_apps = [s for s in statements if re.search(r"\bFROM app\b", s)]
    assert reading_apps
    assert all("WITH RECURSIVE" in s for s in reading_apps)
    assert [s for s in statements if s not in reading_apps and "org_unit" in s] == []


async def test_list_apps_filter_by_leaf_org_unit(db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    leaf = await make_org_unit(db_session, name="CenterWell", parent_id=root.id)
    brand = await make_brand(db_session)
    await make_app(db_session, slug="root-app", brand_id=brand.id, org_unit_id=root.id)
    await make_app(db_session, slug="leaf-app", brand_id=brand.id, org_unit_id=leaf.id)
    page = await app_service.list_apps(db_session, org_unit_id=[leaf.id])
    assert len(page.items) == 1
    assert page.items[0].slug == "leaf-app"


async def test_list_apps_filter_by_multiple_org_units(db_session: AsyncSession) -> None:
    top = await make_org_unit(db_session, name="Top")
    branch_a = await make_org_unit(db_session, name="CenterWell", parent_id=top.id)
    branch_b = await make_org_unit(db_session, name="Pharmacy", parent_id=top.id)
    other = await make_org_unit(db_session, name="Other", parent_id=top.id)
    brand = await make_brand(db_session)
    await make_app(db_session, slug="a-app", brand_id=brand.id, org_unit_id=branch_a.id)
    await make_app(db_session, slug="b-app", brand_id=brand.id, org_unit_id=branch_b.id)
    await make_app(db_session, slug="other-app", brand_id=brand.id, org_unit_id=other.id)
    page = await app_service.list_apps(db_session, org_unit_id=[branch_a.id, branch_b.id])
    assert len(page.items) == 2
    slugs = {a.slug for a in page.items}
    assert slugs == {"a-app", "b-app"}


async def test_list_apps_filter_org_unit_empty_subtree(db_session: AsyncSession) -> None:
    top = await make_org_unit(db_session, name="Top")
    empty = await make_org_unit(db_session, name="Empty", parent_id=top.id)
    other = await make_org_unit(db_session, name="Other", parent_id=top.id)
    brand = await make_brand(db_session)
    await make_app(db_session, slug="other-app", brand_id=brand.id, org_unit_id=other.id)
    page = await app_service.list_apps(db_session, org_unit_id=[empty.id])
    assert len(page.items) == 0


async def test_list_apps_combined_brand_and_org_unit(db_session: AsyncSession) -> None:
    top = await make_org_unit(db_session, name="Top")
    root = await make_org_unit(db_session, name="Humana", parent_id=top.id)
    child = await make_org_unit(db_session, name="CenterWell", parent_id=root.id)
    humana = await make_brand(db_session, name="Humana")
    go365 = await make_brand(db_session, name="Go365")
    await make_app(db_session, slug="match", brand_id=humana.id, org_unit_id=child.id)
    await make_app(db_session, slug="wrong-brand", brand_id=go365.id, org_unit_id=child.id)
    await make_app(
        db_session,
        slug="wrong-org",
        brand_id=humana.id,
        org_unit_id=(await make_org_unit(db_session, name="Other", parent_id=top.id)).id,
    )
    page = await app_service.list_apps(db_session, brand_id=[humana.id], org_unit_id=[root.id])
    assert len(page.items) == 1
    assert page.items[0].slug == "match"


async def test_update_app_not_found(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    with pytest.raises(NotFoundError, match="App"):
        await app_service.update_app(db_session, 999999, AppUpdate(org_unit_id=org_unit.id))


async def test_delete_app(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    brand = await make_brand(db_session)
    created = await make_app(db_session, brand_id=brand.id, org_unit_id=org_unit.id)
    await app_service.delete_app(db_session, created.id)
    with pytest.raises(NotFoundError):
        await app_service.get_app(db_session, created.id)


async def test_delete_app_cascades_dependents(db_session: AsyncSession) -> None:
    app = await make_app_with_org_unit(db_session)
    app_id = app.id
    await make_scan_run(db_session, app_id=app_id)
    await make_score_snapshot(db_session, app_id=app_id)
    await app_service.delete_app(db_session, app_id)
    scan_runs = await db_session.execute(select(ScanRun).where(ScanRun.app_id == app_id))
    assert scan_runs.scalars().all() == []
    snapshots = await db_session.execute(select(ScoreSnapshot).where(ScoreSnapshot.app_id == app_id))
    assert snapshots.scalars().all() == []


async def test_update_app_org_unit(db_session: AsyncSession) -> None:
    brand = await make_brand(db_session)
    org_unit_a = await make_org_unit(db_session, name="Org A")
    org_unit_b = await make_org_unit(db_session, name="Org B", parent_id=org_unit_a.id)
    app = await make_app(db_session, brand_id=brand.id, org_unit_id=org_unit_a.id)
    updated = await app_service.update_app(db_session, app.id, AppUpdate(org_unit_id=org_unit_b.id))
    assert updated.org_unit_id == org_unit_b.id


async def test_update_app_same_org_unit_no_rollup(db_session: AsyncSession) -> None:
    brand = await make_brand(db_session)
    org_unit = await make_org_unit(db_session)
    app = await make_app(db_session, brand_id=brand.id, org_unit_id=org_unit.id)
    await app_service.update_app(db_session, app.id, AppUpdate(org_unit_id=org_unit.id))
    result = await db_session.execute(select(ScoreSnapshot).where(ScoreSnapshot.org_unit_id == org_unit.id))
    assert result.scalar_one_or_none() is None


async def test_update_app_org_unit_not_found(db_session: AsyncSession) -> None:
    brand = await make_brand(db_session)
    org_unit = await make_org_unit(db_session)
    app = await make_app(db_session, brand_id=brand.id, org_unit_id=org_unit.id)
    with pytest.raises(NotFoundError, match="Org unit"):
        await app_service.update_app(db_session, app.id, AppUpdate(org_unit_id=999999))


async def test_delete_app_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError, match="App"):
        await app_service.delete_app(db_session, 999999)
