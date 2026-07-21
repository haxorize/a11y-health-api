import pytest
from pytest import approx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import (
    CircularReferenceError,
    DuplicateRootError,
    HasDependentsError,
    NotFoundError,
)
from a11y_health.models.org_unit import UQ_ORG_UNIT_SINGLE_ROOT, OrgUnit
from a11y_health.schemas.org_unit import OrgUnitCreate, OrgUnitUpdate
from a11y_health.services import org_unit as org_unit_service
from a11y_health.services._org_subtree import get_descendant_ids
from tests.factories import latest_ou_snapshot, make_app, make_org_unit, make_score_snapshot


async def test_create_org_unit(db_session: AsyncSession) -> None:
    org_unit = await org_unit_service.create_org_unit(db_session, OrgUnitCreate(name="Humana"))
    assert org_unit.name == "Humana"
    assert org_unit.parent_id is None
    assert org_unit.id is not None


async def test_create_org_unit_with_parent(db_session: AsyncSession) -> None:
    parent = await make_org_unit(db_session, name="Humana")
    child = await org_unit_service.create_org_unit(db_session, OrgUnitCreate(name="CenterWell", parent_id=parent.id))
    assert child.parent_id == parent.id


async def test_create_second_root_org_unit_rejected(db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    with pytest.raises(DuplicateRootError, match=f"Org unit {root.id} is already the top-level"):
        await org_unit_service.create_org_unit(db_session, OrgUnitCreate(name="Shadow Humana"))


async def test_schema_rejects_second_root_bypassing_service(db_session: AsyncSession) -> None:
    await make_org_unit(db_session, name="Humana")
    db_session.add(OrgUnit(name="Shadow Humana", parent_id=None))
    with pytest.raises(IntegrityError, match=UQ_ORG_UNIT_SINGLE_ROOT):
        await db_session.flush()


async def test_create_root_race_translates_integrity_error(db_session: AsyncSession, mocker) -> None:
    await make_org_unit(db_session, name="Humana")
    # Simulate losing the create/create race: the pre-check saw no root, but one landed before our flush.
    mocker.patch.object(org_unit_service, "_check_no_other_root", new_callable=mocker.AsyncMock)
    with pytest.raises(DuplicateRootError, match="A top-level org unit already exists"):
        await org_unit_service.create_org_unit(db_session, OrgUnitCreate(name="Shadow Humana"))


async def test_create_org_unit_with_invalid_parent(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError, match="Org unit"):
        await org_unit_service.create_org_unit(db_session, OrgUnitCreate(name="Orphan", parent_id=999999))


async def test_list_org_units(db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    await make_org_unit(db_session, name="CenterWell", parent_id=root.id)
    result = await org_unit_service.list_org_units(db_session)
    assert len(result) == 2


async def test_get_org_unit(db_session: AsyncSession) -> None:
    created = await make_org_unit(db_session, name="Humana")
    fetched = await org_unit_service.get_org_unit(db_session, created.id)
    assert fetched.id == created.id
    assert fetched.name == "Humana"


async def test_get_org_unit_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError, match="Org unit"):
        await org_unit_service.get_org_unit(db_session, 999999)


async def test_update_org_unit(db_session: AsyncSession) -> None:
    created = await make_org_unit(db_session, name="Humana")
    updated = await org_unit_service.update_org_unit(db_session, created.id, OrgUnitUpdate(name="Humana Inc."))
    assert updated.name == "Humana Inc."
    assert updated.id == created.id


async def test_update_org_unit_with_invalid_parent(db_session: AsyncSession) -> None:
    created = await make_org_unit(db_session, name="Humana")
    with pytest.raises(NotFoundError, match="Org unit"):
        await org_unit_service.update_org_unit(db_session, created.id, OrgUnitUpdate(parent_id=999999))


async def test_reparent_to_parentless_rejected_when_root_exists(db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    child = await make_org_unit(db_session, name="CenterWell", parent_id=root.id)
    with pytest.raises(DuplicateRootError, match=f"Org unit {root.id} is already the top-level"):
        await org_unit_service.update_org_unit(db_session, child.id, OrgUnitUpdate(parent_id=None))


async def test_reparent_race_translates_integrity_error(db_session: AsyncSession, mocker) -> None:
    root = await make_org_unit(db_session, name="Humana")
    child = await make_org_unit(db_session, name="CenterWell", parent_id=root.id)
    # Simulate losing the reparent race: the pre-check passed, but a root landed before our flush.
    mocker.patch.object(org_unit_service, "_check_no_other_root", new_callable=mocker.AsyncMock)
    with pytest.raises(DuplicateRootError, match="A top-level org unit already exists"):
        await org_unit_service.update_org_unit(db_session, child.id, OrgUnitUpdate(parent_id=None))


async def test_update_root_with_null_parent_is_noop(db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    updated = await org_unit_service.update_org_unit(db_session, root.id, OrgUnitUpdate(parent_id=None))
    assert updated.parent_id is None


async def test_update_org_unit_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError, match="Org unit"):
        await org_unit_service.update_org_unit(db_session, 999999, OrgUnitUpdate(name="Ghost"))


async def test_delete_org_unit(db_session: AsyncSession) -> None:
    created = await make_org_unit(db_session, name="Humana")
    await org_unit_service.delete_org_unit(db_session, created.id)
    with pytest.raises(NotFoundError):
        await org_unit_service.get_org_unit(db_session, created.id)


async def test_delete_org_unit_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError, match="Org unit"):
        await org_unit_service.delete_org_unit(db_session, 999999)


async def test_delete_org_unit_with_apps_rejected(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session, name="Humana")
    await make_app(db_session, slug="blocker-app", org_unit_id=org_unit.id)
    with pytest.raises(HasDependentsError, match="dependent"):
        await org_unit_service.delete_org_unit(db_session, org_unit.id)


async def test_delete_org_unit_with_score_snapshots_rejected(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session, name="Humana")
    await make_score_snapshot(db_session, org_unit_id=org_unit.id)
    with pytest.raises(HasDependentsError, match="dependent"):
        await org_unit_service.delete_org_unit(db_session, org_unit.id)


async def test_delete_org_unit_with_children_rejected(db_session: AsyncSession) -> None:
    parent = await make_org_unit(db_session, name="Humana")
    await make_org_unit(db_session, name="CenterWell", parent_id=parent.id)
    with pytest.raises(HasDependentsError, match="dependent"):
        await org_unit_service.delete_org_unit(db_session, parent.id)


async def test_delete_refusal_leaves_transaction_usable(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session, name="Humana")
    app = await make_app(db_session, slug="blocker-app", org_unit_id=org_unit.id)
    with pytest.raises(HasDependentsError):
        await org_unit_service.delete_org_unit(db_session, org_unit.id)
    # Clearing the dependent and retrying in the same transaction succeeds.
    await db_session.delete(app)
    await db_session.flush()
    await org_unit_service.delete_org_unit(db_session, org_unit.id)
    with pytest.raises(NotFoundError):
        await org_unit_service.get_org_unit(db_session, org_unit.id)


async def test_get_ancestors_returns_path_to_root(db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    middle = await make_org_unit(db_session, name="CenterWell", parent_id=root.id)
    leaf = await make_org_unit(db_session, name="Primary Care", parent_id=middle.id)
    ancestors = await org_unit_service.get_ancestors(db_session, leaf.id)
    assert [a.id for a in ancestors] == [middle.id, root.id]


async def test_get_ancestors_root_has_no_ancestors(db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    ancestors = await org_unit_service.get_ancestors(db_session, root.id)
    assert ancestors == []


async def test_get_ancestors_not_found(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError, match="Org unit"):
        await org_unit_service.get_ancestors(db_session, 999999)


async def test_get_descendant_ids_leaf_returns_self(db_session: AsyncSession) -> None:
    leaf = await make_org_unit(db_session, name="Leaf")
    result = await get_descendant_ids(db_session, [leaf.id])
    assert result == {leaf.id}


async def test_get_descendant_ids_deep_hierarchy(db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    child = await make_org_unit(db_session, name="CenterWell", parent_id=root.id)
    grandchild = await make_org_unit(db_session, name="Primary Care", parent_id=child.id)
    great_grandchild = await make_org_unit(db_session, name="Clinic", parent_id=grandchild.id)
    result = await get_descendant_ids(db_session, [root.id])
    assert result == {root.id, child.id, grandchild.id, great_grandchild.id}


async def test_get_descendant_ids_multiple_inputs_with_overlap(db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    branch_a = await make_org_unit(db_session, name="CenterWell", parent_id=root.id)
    branch_b = await make_org_unit(db_session, name="Pharmacy", parent_id=root.id)
    leaf_a = await make_org_unit(db_session, name="Primary Care", parent_id=branch_a.id)
    result = await get_descendant_ids(db_session, [branch_a.id, branch_b.id])
    assert result == {branch_a.id, branch_b.id, leaf_a.id}


async def test_get_descendant_ids_empty_input(db_session: AsyncSession) -> None:
    result = await get_descendant_ids(db_session, [])
    assert result == set()


async def test_update_rejects_self_as_parent(db_session: AsyncSession) -> None:
    org_unit = await make_org_unit(db_session, name="Humana")
    with pytest.raises(CircularReferenceError):
        await org_unit_service.update_org_unit(db_session, org_unit.id, OrgUnitUpdate(parent_id=org_unit.id))


async def test_update_rejects_descendant_as_parent(db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    child = await make_org_unit(db_session, name="CenterWell", parent_id=root.id)
    grandchild = await make_org_unit(db_session, name="Primary Care", parent_id=child.id)
    with pytest.raises(CircularReferenceError):
        await org_unit_service.update_org_unit(db_session, root.id, OrgUnitUpdate(parent_id=grandchild.id))


async def test_reparent_updates_ancestor_path(db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    branch_a = await make_org_unit(db_session, name="CenterWell", parent_id=root.id)
    branch_b = await make_org_unit(db_session, name="Pharmacy", parent_id=root.id)
    leaf = await make_org_unit(db_session, name="Primary Care", parent_id=branch_a.id)
    await org_unit_service.update_org_unit(db_session, leaf.id, OrgUnitUpdate(parent_id=branch_b.id))
    ancestors = await org_unit_service.get_ancestors(db_session, leaf.id)
    assert [a.id for a in ancestors] == [branch_b.id, root.id]


async def test_reparent_triggers_rollup(db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    branch_a = await make_org_unit(db_session, name="CenterWell", parent_id=root.id)
    branch_b = await make_org_unit(db_session, name="Pharmacy", parent_id=root.id)

    app = await make_app(db_session, name="App", slug="app-reparent", org_unit_id=branch_a.id)
    await make_score_snapshot(
        db_session,
        app_id=app.id,
        score=0.6,
        total_pages=3,
        total_violations=2,
        pages_with_violations=1,
        pages_with_critical_violations=0,
    )
    await make_score_snapshot(
        db_session,
        org_unit_id=branch_a.id,
        score=0.6,
        total_pages=3,
        total_violations=2,
        pages_with_violations=1,
        pages_with_critical_violations=0,
    )

    await org_unit_service.update_org_unit(db_session, branch_a.id, OrgUnitUpdate(parent_id=branch_b.id))

    snapshot = await latest_ou_snapshot(db_session, branch_b.id)
    assert snapshot.score == approx(0.6)
