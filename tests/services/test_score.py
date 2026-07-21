from datetime import UTC, datetime

import pytest
from pytest import approx
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import NotFoundError
from a11y_health.models.enums import ScoreSnapshotOwnerType
from a11y_health.services import score as score_service
from a11y_health.services import score_snapshot as score_snapshot_service
from tests.factories import (
    latest_brand_snapshot,
    make_app,
    make_app_with_org_unit,
    make_brand,
    make_org_unit,
    make_score_snapshot,
)


async def test_list_latest_scores_returns_one_latest_snapshot_per_app(db_session: AsyncSession) -> None:
    app_a = await make_app_with_org_unit(db_session, org_name="Org A", app_name="App A", slug="app-a")
    app_b = await make_app_with_org_unit(db_session, org_name="Org B", app_name="App B", slug="app-b")
    # no snapshots — must be absent from the result, not null-filled
    await make_app_with_org_unit(db_session, org_name="Org C", app_name="App C", slug="app-c")

    await make_score_snapshot(db_session, app_id=app_a.id, score=0.5, snapshot_at=datetime(2026, 4, 1, tzinfo=UTC))
    latest_a = await make_score_snapshot(
        db_session, app_id=app_a.id, score=0.9, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )
    latest_b = await make_score_snapshot(
        db_session, app_id=app_b.id, score=0.7, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )

    page = await score_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.APP)

    assert {(s.app_id, s.id) for s in page.items} == {(app_a.id, latest_a.id), (app_b.id, latest_b.id)}
    assert page.next_cursor is None


async def test_latest_selection_matches_rollup_after_out_of_order_import(db_session: AsyncSession) -> None:
    brand = await make_brand(db_session)
    app_a = await make_app_with_org_unit(db_session, org_name="Org A", slug="app-a", brand_id=brand.id)
    app_b = await make_app_with_org_unit(db_session, org_name="Org B", slug="app-b", brand_id=brand.id)

    # App A: newest observation ingested first; a historical backfill arrives later
    # (higher id, older snapshot_at) and must not displace it
    latest_a = await make_score_snapshot(
        db_session, app_id=app_a.id, score=0.9, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )
    await make_score_snapshot(db_session, app_id=app_a.id, score=0.2, snapshot_at=datetime(2026, 3, 1, tzinfo=UTC))

    # App B: identical snapshot_at — the higher id wins
    await make_score_snapshot(db_session, app_id=app_b.id, score=0.4, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC))
    latest_b = await make_score_snapshot(
        db_session, app_id=app_b.id, score=0.6, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )

    page = await score_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.APP)
    assert {(s.app_id, s.id) for s in page.items} == {(app_a.id, latest_a.id), (app_b.id, latest_b.id)}

    # Parity: the Brand Rollup aggregates exactly the snapshots served above —
    # its score is the mean of theirs (0.9 and 0.6), not of the backfill/tie losers
    await score_snapshot_service.rollup_brand_scores(db_session, brand.id)
    brand_snapshot = await latest_brand_snapshot(db_session, brand.id)
    assert brand_snapshot.score == approx((0.9 + 0.6) / 2)


async def test_served_owner_not_repeated_when_import_lands_mid_walk(db_session: AsyncSession) -> None:
    app_a = await make_app_with_org_unit(db_session, org_name="Org A", app_name="App A", slug="app-a")
    app_b = await make_app_with_org_unit(db_session, org_name="Org B", app_name="App B", slug="app-b")
    await make_score_snapshot(db_session, app_id=app_a.id, score=0.5, snapshot_at=datetime(2026, 4, 1, tzinfo=UTC))
    latest_b = await make_score_snapshot(
        db_session, app_id=app_b.id, score=0.7, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )

    first = await score_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.APP, limit=1)
    assert [s.app_id for s in first.items] == [app_a.id]

    # a scan for the already-served app completes before the next page is fetched
    await make_score_snapshot(db_session, app_id=app_a.id, score=0.9, snapshot_at=datetime(2026, 4, 5, tzinfo=UTC))

    second = await score_service.list_latest_scores(
        db_session, ScoreSnapshotOwnerType.APP, cursor=first.next_cursor, limit=1
    )
    assert [(s.app_id, s.id) for s in second.items] == [(app_b.id, latest_b.id)]
    assert second.next_cursor is None


async def test_list_latest_scores_owner_id_filter_returns_only_requested_owners(db_session: AsyncSession) -> None:
    app_a = await make_app_with_org_unit(db_session, org_name="Org A", app_name="App A", slug="app-a")
    app_b = await make_app_with_org_unit(db_session, org_name="Org B", app_name="App B", slug="app-b")
    app_c = await make_app_with_org_unit(db_session, org_name="Org C", app_name="App C", slug="app-c")

    snapshot_a = await make_score_snapshot(
        db_session, app_id=app_a.id, score=0.9, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )
    snapshot_b = await make_score_snapshot(
        db_session, app_id=app_b.id, score=0.7, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )
    await make_score_snapshot(db_session, app_id=app_c.id, score=0.6, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC))

    page = await score_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.APP, owner_id=[app_a.id, app_b.id])

    assert {(s.app_id, s.id) for s in page.items} == {(app_a.id, snapshot_a.id), (app_b.id, snapshot_b.id)}
    assert page.next_cursor is None


async def test_list_latest_scores_owner_id_filter_ignores_unknown_and_never_scored_ids(
    db_session: AsyncSession,
) -> None:
    scored = await make_app_with_org_unit(db_session, org_name="Org A", app_name="App A", slug="app-a")
    # exists but has no snapshots — filtering on it yields nothing, not an error
    never_scored = await make_app_with_org_unit(db_session, org_name="Org B", app_name="App B", slug="app-b")

    latest = await make_score_snapshot(
        db_session, app_id=scored.id, score=0.9, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )

    page = await score_service.list_latest_scores(
        db_session, ScoreSnapshotOwnerType.APP, owner_id=[scored.id, never_scored.id, 999999]
    )

    assert [(s.app_id, s.id) for s in page.items] == [(scored.id, latest.id)]


async def test_list_latest_scores_owner_id_filter_composes_with_cursor_pagination(db_session: AsyncSession) -> None:
    app_a = await make_app_with_org_unit(db_session, org_name="Org A", app_name="App A", slug="app-a")
    excluded = await make_app_with_org_unit(db_session, org_name="Org B", app_name="App B", slug="app-b")
    app_c = await make_app_with_org_unit(db_session, org_name="Org C", app_name="App C", slug="app-c")

    latest_a = await make_score_snapshot(
        db_session, app_id=app_a.id, score=0.9, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )
    await make_score_snapshot(db_session, app_id=excluded.id, score=0.7, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC))
    latest_c = await make_score_snapshot(
        db_session, app_id=app_c.id, score=0.6, snapshot_at=datetime(2026, 4, 1, tzinfo=UTC)
    )

    requested = [app_a.id, app_c.id]
    first = await score_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.APP, owner_id=requested, limit=1)
    assert [(s.app_id, s.id) for s in first.items] == [(app_a.id, latest_a.id)]
    assert first.next_cursor is not None

    # the excluded owner sits between the two requested ids in keyset order and must not surface mid-walk
    second = await score_service.list_latest_scores(
        db_session, ScoreSnapshotOwnerType.APP, owner_id=requested, cursor=first.next_cursor, limit=1
    )
    assert [(s.app_id, s.id) for s in second.items] == [(app_c.id, latest_c.id)]
    assert second.next_cursor is None


async def test_list_latest_scores_owner_id_filter_is_exact_match_for_rollup_owners(db_session: AsyncSession) -> None:
    # No descendant expansion, unlike list_apps' org_unit_id: the parent's rollup
    # snapshot already aggregates the child's, so the child must not surface.
    parent = await make_org_unit(db_session, name="Parent")
    child = await make_org_unit(db_session, name="Child", parent_id=parent.id)

    parent_snapshot = await make_score_snapshot(
        db_session, org_unit_id=parent.id, score=0.8, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )
    await make_score_snapshot(db_session, org_unit_id=child.id, score=0.6, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC))

    page = await score_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.ORG_UNIT, owner_id=[parent.id])

    assert [(s.org_unit_id, s.id) for s in page.items] == [(parent.id, parent_snapshot.id)]


async def test_list_latest_scores_filters_by_owner_type(db_session: AsyncSession) -> None:
    brand = await make_brand(db_session)
    app = await make_app_with_org_unit(db_session, org_name="Org A", slug="app-a", brand_id=brand.id)

    app_snapshot = await make_score_snapshot(
        db_session, app_id=app.id, score=0.9, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )
    org_unit_snapshot = await make_score_snapshot(
        db_session, org_unit_id=app.org_unit_id, score=0.8, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )
    brand_snapshot = await make_score_snapshot(
        db_session, brand_id=brand.id, score=0.7, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )

    for owner_type, expected in [
        (ScoreSnapshotOwnerType.APP, app_snapshot),
        (ScoreSnapshotOwnerType.ORG_UNIT, org_unit_snapshot),
        (ScoreSnapshotOwnerType.BRAND, brand_snapshot),
    ]:
        page = await score_service.list_latest_scores(db_session, owner_type)
        assert [s.id for s in page.items] == [expected.id]


async def test_under_org_unit_scope_serves_apps_across_the_whole_subtree(db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Root")
    scoped = await make_org_unit(db_session, name="Scoped", parent_id=root.id)
    child = await make_org_unit(db_session, name="Child", parent_id=scoped.id)
    sibling = await make_org_unit(db_session, name="Sibling", parent_id=root.id)

    own_app = await make_app(db_session, name="Own", slug="own", org_unit_id=scoped.id)
    child_app = await make_app(db_session, name="Deep", slug="deep", org_unit_id=child.id)
    outside_app = await make_app(db_session, name="Outside", slug="outside", org_unit_id=sibling.id)

    own_latest = await make_score_snapshot(
        db_session, app_id=own_app.id, score=0.9, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )
    child_latest = await make_score_snapshot(
        db_session, app_id=child_app.id, score=0.7, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )
    await make_score_snapshot(
        db_session, app_id=outside_app.id, score=0.5, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )

    page = await score_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.APP, under_org_unit_id=scoped.id)

    assert {(s.app_id, s.id) for s in page.items} == {(own_app.id, own_latest.id), (child_app.id, child_latest.id)}


async def test_under_org_unit_scope_serves_strict_descendant_units_not_the_unit_itself(
    db_session: AsyncSession,
) -> None:
    root = await make_org_unit(db_session, name="Root")
    scoped = await make_org_unit(db_session, name="Scoped", parent_id=root.id)
    child = await make_org_unit(db_session, name="Child", parent_id=scoped.id)
    grandchild = await make_org_unit(db_session, name="Grandchild", parent_id=child.id)
    sibling = await make_org_unit(db_session, name="Sibling", parent_id=root.id)

    # the scoped unit's own snapshot must NOT appear — "under" is strictly below
    await make_score_snapshot(
        db_session, org_unit_id=scoped.id, score=0.9, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )
    child_latest = await make_score_snapshot(
        db_session, org_unit_id=child.id, score=0.7, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )
    grandchild_latest = await make_score_snapshot(
        db_session, org_unit_id=grandchild.id, score=0.6, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )
    await make_score_snapshot(
        db_session, org_unit_id=sibling.id, score=0.5, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )

    page = await score_service.list_latest_scores(
        db_session, ScoreSnapshotOwnerType.ORG_UNIT, under_org_unit_id=scoped.id
    )

    assert {(s.org_unit_id, s.id) for s in page.items} == {
        (child.id, child_latest.id),
        (grandchild.id, grandchild_latest.id),
    }


async def test_under_org_unit_scope_on_a_leaf_unit_serves_an_empty_page(db_session: AsyncSession) -> None:
    # A leaf's strict-descendant set is empty — the scoped page must be too,
    # exercising the empty-IN rendering of `subtree - {self}`.
    root = await make_org_unit(db_session, name="Root")
    leaf = await make_org_unit(db_session, name="Leaf", parent_id=root.id)
    await make_score_snapshot(db_session, org_unit_id=leaf.id, score=0.9, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC))
    await make_score_snapshot(db_session, org_unit_id=root.id, score=0.8, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC))

    page = await score_service.list_latest_scores(
        db_session, ScoreSnapshotOwnerType.ORG_UNIT, under_org_unit_id=leaf.id
    )

    assert page.items == []


async def test_under_org_unit_scope_serves_no_brand_owners(db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Root")
    scoped = await make_org_unit(db_session, name="Scoped", parent_id=root.id)
    brand = await make_brand(db_session)
    # the brand even owns an app inside the subtree — still not "under" the unit:
    # brands have no org-tree placement, so the scoped brand-owner set is empty
    await make_app(db_session, name="In Subtree", slug="in-subtree", brand_id=brand.id, org_unit_id=scoped.id)
    await make_score_snapshot(db_session, brand_id=brand.id, score=0.8, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC))

    page = await score_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.BRAND, under_org_unit_id=scoped.id)

    assert page.items == []


async def test_under_org_unit_scope_intersects_with_owner_id_filter(db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Root")
    scoped = await make_org_unit(db_session, name="Scoped", parent_id=root.id)
    sibling = await make_org_unit(db_session, name="Sibling", parent_id=root.id)

    inside_requested = await make_app(db_session, name="In R", slug="in-r", org_unit_id=scoped.id)
    inside_unrequested = await make_app(db_session, name="In U", slug="in-u", org_unit_id=scoped.id)
    outside_requested = await make_app(db_session, name="Out R", slug="out-r", org_unit_id=sibling.id)

    kept = await make_score_snapshot(
        db_session, app_id=inside_requested.id, score=0.9, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )
    await make_score_snapshot(
        db_session, app_id=inside_unrequested.id, score=0.7, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )
    await make_score_snapshot(
        db_session, app_id=outside_requested.id, score=0.5, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )

    page = await score_service.list_latest_scores(
        db_session,
        ScoreSnapshotOwnerType.APP,
        owner_id=[inside_requested.id, outside_requested.id],
        under_org_unit_id=scoped.id,
    )

    assert [(s.app_id, s.id) for s in page.items] == [(inside_requested.id, kept.id)]


async def test_under_org_unit_scope_requires_the_unit_to_exist(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await score_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.APP, under_org_unit_id=999999)


async def test_direct_only_narrows_the_org_unit_scope_to_direct_children(db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Root")
    scoped = await make_org_unit(db_session, name="Scoped", parent_id=root.id)
    child = await make_org_unit(db_session, name="Child", parent_id=scoped.id)
    grandchild = await make_org_unit(db_session, name="Grandchild", parent_id=child.id)
    sibling = await make_org_unit(db_session, name="Sibling", parent_id=root.id)

    # the scoped unit's own snapshot stays excluded — direct_only narrows the
    # strict-descendant scope, it never re-adds the unit itself
    await make_score_snapshot(
        db_session, org_unit_id=scoped.id, score=0.9, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )
    child_latest = await make_score_snapshot(
        db_session, org_unit_id=child.id, score=0.7, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )
    await make_score_snapshot(
        db_session, org_unit_id=grandchild.id, score=0.6, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )
    await make_score_snapshot(
        db_session, org_unit_id=sibling.id, score=0.5, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )

    page = await score_service.list_latest_scores(
        db_session, ScoreSnapshotOwnerType.ORG_UNIT, under_org_unit_id=scoped.id, direct_only=True
    )

    assert {(s.org_unit_id, s.id) for s in page.items} == {(child.id, child_latest.id)}


async def test_direct_only_narrows_the_app_scope_to_apps_placed_on_the_unit_itself(
    db_session: AsyncSession,
) -> None:
    root = await make_org_unit(db_session, name="Root")
    scoped = await make_org_unit(db_session, name="Scoped", parent_id=root.id)
    child = await make_org_unit(db_session, name="Child", parent_id=scoped.id)

    own_app = await make_app(db_session, name="Own", slug="own", org_unit_id=scoped.id)
    descendant_app = await make_app(db_session, name="Deep", slug="deep", org_unit_id=child.id)

    own_latest = await make_score_snapshot(
        db_session, app_id=own_app.id, score=0.9, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )
    await make_score_snapshot(
        db_session, app_id=descendant_app.id, score=0.7, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )

    page = await score_service.list_latest_scores(
        db_session, ScoreSnapshotOwnerType.APP, under_org_unit_id=scoped.id, direct_only=True
    )

    assert {(s.app_id, s.id) for s in page.items} == {(own_app.id, own_latest.id)}


async def test_direct_only_serves_no_brand_owners_either(db_session: AsyncSession) -> None:
    # Brands have no org-tree placement at any depth: the direct scope must
    # stay empty exactly like the subtree scope. Guards any restructuring
    # that resolves scope depth before owner-type dispatch.
    root = await make_org_unit(db_session, name="Root")
    scoped = await make_org_unit(db_session, name="Scoped", parent_id=root.id)
    brand = await make_brand(db_session)
    await make_app(db_session, name="On Unit", slug="on-unit", brand_id=brand.id, org_unit_id=scoped.id)
    await make_score_snapshot(db_session, brand_id=brand.id, score=0.8, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC))

    page = await score_service.list_latest_scores(
        db_session, ScoreSnapshotOwnerType.BRAND, under_org_unit_id=scoped.id, direct_only=True
    )

    assert page.items == []


async def test_direct_only_without_the_scope_is_ignored(db_session: AsyncSession) -> None:
    # direct_only refines under_org_unit_id; with no scope there is nothing to
    # refine, and the honest answer is the unscoped listing — not an error and
    # not an empty page (same posture as ADR 0034's brand-scope call).
    root = await make_org_unit(db_session, name="Root")
    child = await make_org_unit(db_session, name="Child", parent_id=root.id)
    app_on_root = await make_app(db_session, name="On Root", slug="on-root", org_unit_id=root.id)
    app_on_child = await make_app(db_session, name="On Child", slug="on-child", org_unit_id=child.id)

    root_latest = await make_score_snapshot(
        db_session, app_id=app_on_root.id, score=0.9, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )
    child_latest = await make_score_snapshot(
        db_session, app_id=app_on_child.id, score=0.7, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )

    page = await score_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.APP, direct_only=True)

    assert {(s.app_id, s.id) for s in page.items} == {
        (app_on_root.id, root_latest.id),
        (app_on_child.id, child_latest.id),
    }


async def test_brand_scope_serves_the_brands_apps_wherever_they_sit(db_session: AsyncSession) -> None:
    # Brand ownership is flat, like the brand rollup: org-tree placement is
    # irrelevant, only App.brand_id decides membership.
    scoped = await make_brand(db_session)
    other = await make_brand(db_session)
    root = await make_org_unit(db_session, name="Root")
    child = await make_org_unit(db_session, name="Child", parent_id=root.id)

    app_on_root = await make_app(db_session, name="On Root", slug="on-root", brand_id=scoped.id, org_unit_id=root.id)
    app_on_child = await make_app(
        db_session, name="On Child", slug="on-child", brand_id=scoped.id, org_unit_id=child.id
    )
    other_app = await make_app(db_session, name="Other", slug="other", brand_id=other.id, org_unit_id=root.id)

    root_latest = await make_score_snapshot(
        db_session, app_id=app_on_root.id, score=0.9, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )
    child_latest = await make_score_snapshot(
        db_session, app_id=app_on_child.id, score=0.7, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )
    await make_score_snapshot(db_session, app_id=other_app.id, score=0.5, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC))

    page = await score_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.APP, brand_id=scoped.id)

    assert {(s.app_id, s.id) for s in page.items} == {
        (app_on_root.id, root_latest.id),
        (app_on_child.id, child_latest.id),
    }


async def test_brand_scope_serves_no_org_unit_owners(db_session: AsyncSession) -> None:
    brand = await make_brand(db_session)
    root = await make_org_unit(db_session, name="Root")
    # the unit even hosts one of the brand's apps — still not brand-owned:
    # org units have no brand, so the scoped org-unit-owner set is empty
    await make_app(db_session, name="Hosted", slug="hosted", brand_id=brand.id, org_unit_id=root.id)
    await make_score_snapshot(db_session, org_unit_id=root.id, score=0.8, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC))

    page = await score_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.ORG_UNIT, brand_id=brand.id)

    assert page.items == []


async def test_brand_scope_serves_no_brand_owners_not_even_the_scoping_brand(db_session: AsyncSession) -> None:
    # A brand isn't owned by a brand, and the scoping brand's own rollup already
    # aggregates the app set being scoped to — same posture as the under-scope
    # excluding the named unit itself. Its rollup row is fetched via owner_id.
    brand = await make_brand(db_session)
    await make_score_snapshot(db_session, brand_id=brand.id, score=0.8, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC))

    page = await score_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.BRAND, brand_id=brand.id)

    assert page.items == []


async def test_brand_scope_intersects_with_owner_id_filter(db_session: AsyncSession) -> None:
    brand = await make_brand(db_session)
    other = await make_brand(db_session)
    root = await make_org_unit(db_session, name="Root")

    in_brand_requested = await make_app(db_session, name="In R", slug="in-r", brand_id=brand.id, org_unit_id=root.id)
    in_brand_unrequested = await make_app(db_session, name="In U", slug="in-u", brand_id=brand.id, org_unit_id=root.id)
    out_of_brand_requested = await make_app(
        db_session, name="Out R", slug="out-r", brand_id=other.id, org_unit_id=root.id
    )

    kept = await make_score_snapshot(
        db_session, app_id=in_brand_requested.id, score=0.9, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )
    await make_score_snapshot(
        db_session, app_id=in_brand_unrequested.id, score=0.7, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )
    await make_score_snapshot(
        db_session, app_id=out_of_brand_requested.id, score=0.5, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )

    page = await score_service.list_latest_scores(
        db_session,
        ScoreSnapshotOwnerType.APP,
        owner_id=[in_brand_requested.id, out_of_brand_requested.id],
        brand_id=brand.id,
    )

    assert [(s.app_id, s.id) for s in page.items] == [(in_brand_requested.id, kept.id)]


async def test_brand_scope_intersects_with_the_under_org_unit_scope(db_session: AsyncSession) -> None:
    brand = await make_brand(db_session)
    root = await make_org_unit(db_session, name="Root")
    scoped = await make_org_unit(db_session, name="Scoped", parent_id=root.id)
    sibling = await make_org_unit(db_session, name="Sibling", parent_id=root.id)

    in_both = await make_app(db_session, name="In Both", slug="in-both", brand_id=brand.id, org_unit_id=scoped.id)
    in_brand_outside_subtree = await make_app(
        db_session, name="Elsewhere", slug="elsewhere", brand_id=brand.id, org_unit_id=sibling.id
    )
    in_subtree_other_brand = await make_app(db_session, name="Neighbor", slug="neighbor", org_unit_id=scoped.id)

    kept = await make_score_snapshot(
        db_session, app_id=in_both.id, score=0.9, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )
    await make_score_snapshot(
        db_session, app_id=in_brand_outside_subtree.id, score=0.7, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )
    await make_score_snapshot(
        db_session, app_id=in_subtree_other_brand.id, score=0.5, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )

    page = await score_service.list_latest_scores(
        db_session, ScoreSnapshotOwnerType.APP, brand_id=brand.id, under_org_unit_id=scoped.id
    )

    assert [(s.app_id, s.id) for s in page.items] == [(in_both.id, kept.id)]


async def test_brand_scope_requires_the_brand_to_exist(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await score_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.APP, brand_id=999999)
