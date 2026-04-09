import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import DuplicateSlugError, NotFoundError
from a11y_health.models.app import Brand
from a11y_health.schemas.app import AppCreate, AppUpdate
from a11y_health.services import app as app_service
from tests.factories import make_app, make_org_unit


async def test_create_app(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    app = await app_service.create_app(
        db_session, AppCreate(name="MyApp", slug="my-app", brand=Brand.HUMANA, org_unit_id=org_unit.id)
    )
    assert app.name == "MyApp"
    assert app.slug == "my-app"
    assert app.brand == Brand.HUMANA
    assert app.org_unit_id == org_unit.id
    assert app.id is not None


async def test_create_app_invalid_org_unit(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError, match="Org unit"):
        await app_service.create_app(
            db_session, AppCreate(name="MyApp", slug="my-app", brand=Brand.HUMANA, org_unit_id=999999)
        )


async def test_create_app_duplicate_slug(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    await make_app(db_session, slug="taken", org_unit_id=org_unit.id)
    with pytest.raises(DuplicateSlugError, match="taken"):
        await app_service.create_app(
            db_session, AppCreate(name="Another", slug="taken", brand=Brand.HUMANA, org_unit_id=org_unit.id)
        )


async def test_get_app(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    created = await make_app(db_session, org_unit_id=org_unit.id)
    fetched = await app_service.get_app(db_session, created.id)
    assert fetched.id == created.id
    assert fetched.name == created.name


async def test_get_app_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError, match="App"):
        await app_service.get_app(db_session, 999999)


async def test_get_app_by_slug(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    created = await make_app(db_session, slug="find-me", org_unit_id=org_unit.id)
    fetched = await app_service.get_app_by_slug(db_session, "find-me")
    assert fetched.id == created.id


async def test_get_app_by_slug_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError, match="App"):
        await app_service.get_app_by_slug(db_session, "nonexistent")


async def test_list_apps(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    await make_app(db_session, name="App A", slug="app-a", org_unit_id=org_unit.id)
    await make_app(db_session, name="App B", slug="app-b", org_unit_id=org_unit.id)
    result = await app_service.list_apps(db_session)
    assert len(result) == 2


async def test_list_apps_filter_by_brand(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    await make_app(db_session, slug="humana-app", brand=Brand.HUMANA, org_unit_id=org_unit.id)
    await make_app(db_session, slug="go365-app", brand=Brand.GO365, org_unit_id=org_unit.id)
    result = await app_service.list_apps(db_session, brand=Brand.GO365)
    assert len(result) == 1
    assert result[0].brand == Brand.GO365


async def test_list_apps_pagination(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    for i in range(5):
        await make_app(db_session, slug=f"app-{i}", org_unit_id=org_unit.id)
    result = await app_service.list_apps(db_session, offset=1, limit=2)
    assert len(result) == 2


async def test_update_app(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    created = await make_app(db_session, name="Old Name", org_unit_id=org_unit.id)
    updated = await app_service.update_app(db_session, created.id, AppUpdate(name="New Name"))
    assert updated.name == "New Name"
    assert updated.id == created.id


async def test_update_app_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError, match="App"):
        await app_service.update_app(db_session, 999999, AppUpdate(name="Ghost"))


async def test_delete_app(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session)
    created = await make_app(db_session, org_unit_id=org_unit.id)
    await app_service.delete_app(db_session, created.id)
    with pytest.raises(NotFoundError):
        await app_service.get_app(db_session, created.id)


async def test_delete_app_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError, match="App"):
        await app_service.delete_app(db_session, 999999)
