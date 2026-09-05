from datetime import UTC, datetime

import pytest
from pytest import approx
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import ConcurrentRollupError, NotFoundError
from a11y_health.models.enums import ScoreSnapshotOwnerType
from a11y_health.models.score_snapshot import (
    CK_SCORE_SNAPSHOT_OWNER,
    UQ_SCORE_SNAPSHOT_BRAND_SNAPSHOT_AT,
    UQ_SCORE_SNAPSHOT_ORG_UNIT_SNAPSHOT_AT,
    ScoreSnapshot,
)
from a11y_health.services import owner as owner_service
from tests.factories import (
    DEFAULT_SNAPSHOT_AT,
    SCORE_SNAPSHOT_DEFAULTS,
    brand_snapshots,
    build_score_snapshot,
    ingest_and_score,
    latest_brand_snapshot,
    latest_ou_snapshot,
    make_app,
    make_app_with_org_unit,
    make_axe_payload,
    make_brand,
    make_org_unit,
    make_scan_run,
    make_score_snapshot,
    make_violation,
    ou_snapshots,
)


class TestOwnedConstruction:
    def test_app_snapshot_links_its_scan_run(self) -> None:
        snapshot = owner_service.owned(
            ScoreSnapshotOwnerType.APP, 7, scan_run_id=9, **SCORE_SNAPSHOT_DEFAULTS._asdict()
        )

        assert snapshot.app_id == 7
        assert snapshot.scan_run_id == 9
        assert snapshot.org_unit_id is None
        assert snapshot.brand_id is None
        assert snapshot.score == approx(SCORE_SNAPSHOT_DEFAULTS.score)
        assert snapshot.snapshot_at == SCORE_SNAPSHOT_DEFAULTS.snapshot_at

    @pytest.mark.parametrize(
        ("owner_type", "column"),
        [(ScoreSnapshotOwnerType.ORG_UNIT, "org_unit_id"), (ScoreSnapshotOwnerType.BRAND, "brand_id")],
    )
    def test_rollup_owner_snapshot_sets_only_its_column(self, owner_type: ScoreSnapshotOwnerType, column: str) -> None:
        snapshot = owner_service.owned(owner_type, 7, **SCORE_SNAPSHOT_DEFAULTS._asdict())

        assert getattr(snapshot, column) == 7
        others = {"app_id", "org_unit_id", "brand_id"} - {column}
        assert all(getattr(snapshot, other) is None for other in others)
        assert snapshot.scan_run_id is None

    def test_scan_run_link_stays_guarded_to_app_owners(self) -> None:
        with pytest.raises(ValueError, match="scan_run_id"):
            owner_service.owned(ScoreSnapshotOwnerType.ORG_UNIT, 7, scan_run_id=9, **SCORE_SNAPSHOT_DEFAULTS._asdict())


async def test_rollup_refuses_an_app_owner(db_session: AsyncSession) -> None:
    # APP snapshots come from scoring; reaching a rollup with one is a bug.
    with pytest.raises(ValueError, match="scoring"):
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.APP, 1)


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

    page = await owner_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.APP)

    assert {(s.app_id, s.id) for s in page.items} == {(app_a.id, latest_a.id), (app_b.id, latest_b.id)}
    assert page.next_cursor is None


async def test_latest_selection_matches_rollup_after_out_of_order_import(db_session: AsyncSession) -> None:
    brand = await make_brand(db_session)
    app_a = await make_app_with_org_unit(db_session, org_name="Org A", slug="app-a", brand_id=brand.id)
    app_b = await make_app_with_org_unit(db_session, org_name="Org B", slug="app-b", brand_id=brand.id)

    # App A: newest observation ingested first; a historical backfill arrives
    # later (higher id, older snapshot_at) and must not displace it
    latest_a = await make_score_snapshot(
        db_session, app_id=app_a.id, score=0.9, snapshot_at=datetime(2026, 4, 3, tzinfo=UTC)
    )
    await make_score_snapshot(db_session, app_id=app_a.id, score=0.2, snapshot_at=datetime(2026, 3, 1, tzinfo=UTC))

    # App B: identical snapshot_at — the higher id wins
    await make_score_snapshot(db_session, app_id=app_b.id, score=0.4, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC))
    latest_b = await make_score_snapshot(
        db_session, app_id=app_b.id, score=0.6, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )

    page = await owner_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.APP)
    assert {(s.app_id, s.id) for s in page.items} == {(app_a.id, latest_a.id), (app_b.id, latest_b.id)}

    # Parity: the Brand Rollup aggregates exactly the snapshots served above —
    # its score is the mean of theirs (0.9 and 0.6), not of the backfill/tie
    # losers
    await owner_service.rollup(db_session, ScoreSnapshotOwnerType.BRAND, brand.id)
    brand_snapshot = await latest_brand_snapshot(db_session, brand.id)
    assert brand_snapshot.score == approx((0.9 + 0.6) / 2)


async def test_served_owner_not_repeated_when_import_lands_mid_walk(db_session: AsyncSession) -> None:
    app_a = await make_app_with_org_unit(db_session, org_name="Org A", app_name="App A", slug="app-a")
    app_b = await make_app_with_org_unit(db_session, org_name="Org B", app_name="App B", slug="app-b")
    await make_score_snapshot(db_session, app_id=app_a.id, score=0.5, snapshot_at=datetime(2026, 4, 1, tzinfo=UTC))
    latest_b = await make_score_snapshot(
        db_session, app_id=app_b.id, score=0.7, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )

    first = await owner_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.APP, limit=1)
    assert [s.app_id for s in first.items] == [app_a.id]

    # a scan for the already-served app completes before the next page is
    # fetched
    await make_score_snapshot(db_session, app_id=app_a.id, score=0.9, snapshot_at=datetime(2026, 4, 5, tzinfo=UTC))

    second = await owner_service.list_latest_scores(
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

    page = await owner_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.APP, owner_id=[app_a.id, app_b.id])

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

    page = await owner_service.list_latest_scores(
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
    first = await owner_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.APP, owner_id=requested, limit=1)
    assert [(s.app_id, s.id) for s in first.items] == [(app_a.id, latest_a.id)]
    assert first.next_cursor is not None

    # the excluded owner sits between the two requested ids in keyset order and
    # must not surface mid-walk
    second = await owner_service.list_latest_scores(
        db_session, ScoreSnapshotOwnerType.APP, owner_id=requested, cursor=first.next_cursor, limit=1
    )
    assert [(s.app_id, s.id) for s in second.items] == [(app_c.id, latest_c.id)]
    assert second.next_cursor is None


async def test_list_latest_scores_owner_id_filter_is_exact_match_for_rollup_owners(db_session: AsyncSession) -> None:
    # No descendant expansion, unlike list_apps' org_unit_id: the parent's
    # rollup snapshot already aggregates the child's, so the child must not
    # surface.
    parent = await make_org_unit(db_session, name="Parent")
    child = await make_org_unit(db_session, name="Child", parent_id=parent.id)

    parent_snapshot = await make_score_snapshot(
        db_session, org_unit_id=parent.id, score=0.8, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC)
    )
    await make_score_snapshot(db_session, org_unit_id=child.id, score=0.6, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC))

    page = await owner_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.ORG_UNIT, owner_id=[parent.id])

    assert [(s.org_unit_id, s.id) for s in page.items] == [(parent.id, parent_snapshot.id)]


async def test_list_latest_scores_empty_owner_id_list_serves_an_empty_page(db_session: AsyncSession) -> None:
    # "Exactly these owners: none" — an empty filter must not fall through to
    # the unfiltered listing and over-serve every owner.
    org_unit = await make_org_unit(db_session)
    await make_score_snapshot(db_session, org_unit_id=org_unit.id)

    page = await owner_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.ORG_UNIT, owner_id=[])

    assert page.items == []


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
        page = await owner_service.list_latest_scores(db_session, owner_type)
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

    page = await owner_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.APP, under_org_unit_id=scoped.id)

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

    page = await owner_service.list_latest_scores(
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

    page = await owner_service.list_latest_scores(
        db_session, ScoreSnapshotOwnerType.ORG_UNIT, under_org_unit_id=leaf.id
    )

    assert page.items == []


async def test_under_org_unit_scope_serves_no_brand_owners(db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Root")
    scoped = await make_org_unit(db_session, name="Scoped", parent_id=root.id)
    brand = await make_brand(db_session)
    # the brand even owns an app inside the subtree — still not "under" the
    # unit: brands have no org-tree placement, so the scoped brand-owner set is
    # empty
    await make_app(db_session, name="In Subtree", slug="in-subtree", brand_id=brand.id, org_unit_id=scoped.id)
    await make_score_snapshot(db_session, brand_id=brand.id, score=0.8, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC))

    page = await owner_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.BRAND, under_org_unit_id=scoped.id)

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

    page = await owner_service.list_latest_scores(
        db_session,
        ScoreSnapshotOwnerType.APP,
        owner_id=[inside_requested.id, outside_requested.id],
        under_org_unit_id=scoped.id,
    )

    assert [(s.app_id, s.id) for s in page.items] == [(inside_requested.id, kept.id)]


async def test_under_org_unit_scope_requires_the_unit_to_exist(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await owner_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.APP, under_org_unit_id=999999)


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

    page = await owner_service.list_latest_scores(
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

    page = await owner_service.list_latest_scores(
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

    page = await owner_service.list_latest_scores(
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

    page = await owner_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.APP, direct_only=True)

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

    page = await owner_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.APP, brand_id=scoped.id)

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

    page = await owner_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.ORG_UNIT, brand_id=brand.id)

    assert page.items == []


async def test_brand_scope_serves_no_brand_owners_not_even_the_scoping_brand(db_session: AsyncSession) -> None:
    # A brand isn't owned by a brand, and the scoping brand's own rollup already
    # aggregates the app set being scoped to — same posture as the under-scope
    # excluding the named unit itself. Its rollup row is fetched via owner_id.
    brand = await make_brand(db_session)
    await make_score_snapshot(db_session, brand_id=brand.id, score=0.8, snapshot_at=datetime(2026, 4, 2, tzinfo=UTC))

    page = await owner_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.BRAND, brand_id=brand.id)

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

    page = await owner_service.list_latest_scores(
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

    page = await owner_service.list_latest_scores(
        db_session, ScoreSnapshotOwnerType.APP, brand_id=brand.id, under_org_unit_id=scoped.id
    )

    assert [(s.app_id, s.id) for s in page.items] == [(in_both.id, kept.id)]


async def test_brand_scope_requires_the_brand_to_exist(db_session: AsyncSession) -> None:
    with pytest.raises(NotFoundError):
        await owner_service.list_latest_scores(db_session, ScoreSnapshotOwnerType.APP, brand_id=999999)


def test_score_snapshot_column_set_is_pinned() -> None:
    # Canary: a new column must decide whether it joins the same-observation
    # equality basis in _aggregate_values — update the tuple there, then here.
    assert {attr.key for attr in ScoreSnapshot.__mapper__.column_attrs} == {
        "id",
        "app_id",
        "scan_run_id",
        "org_unit_id",
        "brand_id",
        "score",
        "total_violations",
        "total_pages",
        "pages_with_violations",
        "pages_with_critical_violations",
        "snapshot_at",
        "created_at",
        "updated_at",
    }


# Arrange only: the rollup that reads this snapshot stays visible in each
# test body.
async def _score_new_scan_run(
    db_session: AsyncSession,
    app_id: int,
    payloads: list[dict],
    scanned_at: datetime | None = None,
) -> ScoreSnapshot:
    sr = await make_scan_run(db_session, app_id=app_id, scanned_at=scanned_at)
    return await ingest_and_score(db_session, sr.id, payloads)


class TestOrgUnitRollup:
    async def test_single_app_rollup_matches_app_snapshot(self, db_session: AsyncSession) -> None:
        org_unit = await make_org_unit(db_session, name="Parent Org")
        app = await make_app(db_session, name="App A", slug="app-a", org_unit_id=org_unit.id)
        app_snapshot = await _score_new_scan_run(
            db_session, app.id, [make_axe_payload(violations=[make_violation("r1", "serious")])]
        )
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.ORG_UNIT, org_unit.id)

        ou_snapshot = await latest_ou_snapshot(db_session, org_unit.id)
        assert ou_snapshot.score == approx(app_snapshot.score)
        assert ou_snapshot.total_violations == app_snapshot.total_violations
        assert ou_snapshot.total_pages == app_snapshot.total_pages
        assert ou_snapshot.pages_with_violations == app_snapshot.pages_with_violations
        assert ou_snapshot.pages_with_critical_violations == app_snapshot.pages_with_critical_violations

    async def test_two_apps_rollup_averages_scores_sums_counts(self, db_session: AsyncSession) -> None:
        org_unit = await make_org_unit(db_session, name="Parent Org")
        app_a = await make_app(db_session, name="App A", slug="app-a", org_unit_id=org_unit.id)
        app_b = await make_app(db_session, name="App B", slug="app-b", org_unit_id=org_unit.id)

        await _score_new_scan_run(
            db_session,
            app_a.id,
            [make_axe_payload(violations=[make_violation("r1", "serious")])],
            scanned_at=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
        )
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.ORG_UNIT, org_unit.id)
        await _score_new_scan_run(
            db_session,
            app_b.id,
            [make_axe_payload(url="https://example.com/b")],
            scanned_at=datetime(2026, 4, 1, 13, 0, 0, tzinfo=UTC),
        )
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.ORG_UNIT, org_unit.id)

        ou_snapshot = await latest_ou_snapshot(db_session, org_unit.id)

        assert ou_snapshot.score == approx(0.7)
        assert ou_snapshot.total_violations == 1
        assert ou_snapshot.total_pages == 2
        assert ou_snapshot.pages_with_violations == 1
        assert ou_snapshot.pages_with_critical_violations == 0

    async def test_multi_level_tree_cascades_to_root(self, db_session: AsyncSession) -> None:
        root = await make_org_unit(db_session, name="Root")
        middle = await make_org_unit(db_session, name="Middle", parent_id=root.id)
        leaf = await make_org_unit(db_session, name="Leaf", parent_id=middle.id)
        app = await make_app(db_session, name="App", slug="app-leaf", org_unit_id=leaf.id)

        app_snapshot = await _score_new_scan_run(
            db_session, app.id, [make_axe_payload(violations=[make_violation("r1", "serious")])]
        )
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.ORG_UNIT, leaf.id)

        for ou in [leaf, middle, root]:
            ou_snap = await latest_ou_snapshot(db_session, ou.id)
            assert ou_snap.score == approx(app_snapshot.score)
            assert ou_snap.total_violations == app_snapshot.total_violations
            assert ou_snap.total_pages == app_snapshot.total_pages

    async def test_mixed_children_org_units_and_apps(self, db_session: AsyncSession) -> None:
        parent = await make_org_unit(db_session, name="Parent")
        child_ou = await make_org_unit(db_session, name="Child OU", parent_id=parent.id)
        direct_app = await make_app(db_session, name="Direct App", slug="direct", org_unit_id=parent.id)
        nested_app = await make_app(db_session, name="Nested App", slug="nested", org_unit_id=child_ou.id)

        await _score_new_scan_run(
            db_session,
            nested_app.id,
            [make_axe_payload(url="https://example.com/nested")],
            scanned_at=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
        )
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.ORG_UNIT, child_ou.id)
        await _score_new_scan_run(
            db_session,
            direct_app.id,
            [make_axe_payload(url="https://example.com/direct", violations=[make_violation("r1", "critical")])],
            scanned_at=datetime(2026, 4, 1, 13, 0, 0, tzinfo=UTC),
        )
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.ORG_UNIT, parent.id)

        assert (await latest_ou_snapshot(db_session, child_ou.id)).score == approx(1.0)

        parent_snap = await latest_ou_snapshot(db_session, parent.id)
        assert parent_snap.score == approx(0.5)
        assert parent_snap.total_violations == 1
        assert parent_snap.total_pages == 2
        assert parent_snap.pages_with_critical_violations == 1

    async def test_only_latest_app_snapshot_counts(self, db_session: AsyncSession) -> None:
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(db_session, name="App", slug="app-latest", org_unit_id=org_unit.id)

        await _score_new_scan_run(
            db_session,
            app.id,
            [make_axe_payload(violations=[make_violation("r1", "critical")])],
            scanned_at=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
        )
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.ORG_UNIT, org_unit.id)
        await _score_new_scan_run(
            db_session,
            app.id,
            [make_axe_payload(url="https://example.com/b")],
            scanned_at=datetime(2026, 4, 1, 13, 0, 0, tzinfo=UTC),
        )
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.ORG_UNIT, org_unit.id)

        assert (await latest_ou_snapshot(db_session, org_unit.id)).score == approx(1.0)

    async def test_child_app_and_org_unit_with_equal_ids_both_count(self, db_session: AsyncSession) -> None:
        # app.id and org_unit.id come from separate identity sequences, so a
        # child App and a child Org Unit can legitimately share an id value —
        # the latest-per-child partition must keep them apart.
        parent = await make_org_unit(db_session, name="Collide Parent")
        brand = await make_brand(db_session)
        collided_id = 900_000_001
        await db_session.execute(
            text(
                "INSERT INTO org_unit (id, name, parent_id) "
                "OVERRIDING SYSTEM VALUE VALUES (:id, 'Collide OU', :parent_id)"
            ),
            {"id": collided_id, "parent_id": parent.id},
        )
        await db_session.execute(
            text(
                "INSERT INTO app (id, name, slug, brand_id, org_unit_id) "
                "OVERRIDING SYSTEM VALUE VALUES (:id, 'Collide App', 'collide-app', :brand_id, :org_unit_id)"
            ),
            {"id": collided_id, "brand_id": brand.id, "org_unit_id": parent.id},
        )

        await make_score_snapshot(
            db_session, app_id=collided_id, score=0.4, snapshot_at=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
        )
        await make_score_snapshot(
            db_session, org_unit_id=collided_id, score=0.8, snapshot_at=datetime(2026, 4, 1, 13, 0, 0, tzinfo=UTC)
        )

        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.ORG_UNIT, parent.id)

        assert (await latest_ou_snapshot(db_session, parent.id)).score == approx((0.4 + 0.8) / 2)

    async def test_higher_id_wins_when_snapshot_at_ties(self, db_session: AsyncSession) -> None:
        org_unit = await make_org_unit(db_session, name="Tie Org")
        app = await make_app(db_session, name="Tie App", slug="app-tie", org_unit_id=org_unit.id)
        tied_at = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)

        await make_score_snapshot(db_session, app_id=app.id, score=0.2, snapshot_at=tied_at)
        await make_score_snapshot(db_session, app_id=app.id, score=0.8, snapshot_at=tied_at)

        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.ORG_UNIT, org_unit.id)

        assert (await latest_ou_snapshot(db_session, org_unit.id)).score == approx(0.8)


class TestRollupNoChangeRecompute:
    # History keeps one Score Snapshot per distinct observation, not one per
    # trigger (#95).

    async def test_unchanged_recompute_records_nothing_new(self, db_session: AsyncSession) -> None:
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(db_session, name="App", slug="app-nochange", org_unit_id=org_unit.id)
        await _score_new_scan_run(db_session, app.id, [make_axe_payload(violations=[make_violation("r1", "serious")])])
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.ORG_UNIT, org_unit.id)

        # deletion and reparent triggers re-run the rollup with unchanged
        # children
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.ORG_UNIT, org_unit.id)
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.ORG_UNIT, org_unit.id)

        snapshots = await ou_snapshots(db_session, org_unit.id)
        assert len(snapshots) == 1
        assert snapshots[0].score == approx(0.4)

    async def test_changed_aggregate_at_same_observation_time_replaces(self, db_session: AsyncSession) -> None:
        scanned_at = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)
        org_unit = await make_org_unit(db_session, name="Org")
        app_a = await make_app(db_session, name="App A", slug="app-a", org_unit_id=org_unit.id)
        app_b = await make_app(db_session, name="App B", slug="app-b", org_unit_id=org_unit.id)

        await _score_new_scan_run(
            db_session,
            app_a.id,
            [make_axe_payload(violations=[make_violation("r1", "serious")])],
            scanned_at=scanned_at,
        )
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.ORG_UNIT, org_unit.id)
        await _score_new_scan_run(
            db_session,
            app_b.id,
            [make_axe_payload(url="https://example.com/b")],
            scanned_at=scanned_at,
        )
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.ORG_UNIT, org_unit.id)

        snapshots = await ou_snapshots(db_session, org_unit.id)
        assert len(snapshots) == 1
        assert snapshots[0].score == approx(0.7)
        assert snapshots[0].snapshot_at == scanned_at

    async def test_older_scan_completion_reproducing_aggregate_records_nothing_new(
        self, db_session: AsyncSession
    ) -> None:
        # An older scan that doesn't displace the app's latest snapshot leaves
        # the aggregate — values and observation time — unchanged.
        latest_scanned_at = datetime(2026, 4, 2, 12, 0, 0, tzinfo=UTC)
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(db_session, name="App", slug="app-same-mean", org_unit_id=org_unit.id)

        await _score_new_scan_run(
            db_session,
            app.id,
            [make_axe_payload(violations=[make_violation("r1", "serious")])],
            scanned_at=latest_scanned_at,
        )
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.ORG_UNIT, org_unit.id)
        await _score_new_scan_run(
            db_session,
            app.id,
            [make_axe_payload(violations=[make_violation("r1", "serious")])],
            scanned_at=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
        )
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.ORG_UNIT, org_unit.id)

        snapshots = await ou_snapshots(db_session, org_unit.id)
        assert len(snapshots) == 1
        assert snapshots[0].snapshot_at == latest_scanned_at

    async def test_newer_observation_with_unchanged_values_appends(self, db_session: AsyncSession) -> None:
        # A distinct observation is history even when the value didn't move —
        # skipping it would leave the latest snapshot claiming an observation
        # time whose scan may later be deleted.
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(db_session, name="App", slug="app-flat-trend", org_unit_id=org_unit.id)

        await _score_new_scan_run(
            db_session,
            app.id,
            [make_axe_payload(violations=[make_violation("r1", "serious")])],
            scanned_at=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
        )
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.ORG_UNIT, org_unit.id)
        second_scanned_at = datetime(2026, 4, 2, 12, 0, 0, tzinfo=UTC)
        await _score_new_scan_run(
            db_session,
            app.id,
            [make_axe_payload(violations=[make_violation("r1", "serious")])],
            scanned_at=second_scanned_at,
        )
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.ORG_UNIT, org_unit.id)

        snapshots = await ou_snapshots(db_session, org_unit.id)
        assert len(snapshots) == 2
        assert snapshots[-1].snapshot_at == second_scanned_at

    async def test_brand_unchanged_recompute_records_nothing_new(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="Humana")
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(db_session, name="App", slug="app-brand", org_unit_id=org_unit.id, brand_id=brand.id)
        await _score_new_scan_run(db_session, app.id, [make_axe_payload(violations=[make_violation("r1", "serious")])])
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.BRAND, brand.id)

        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.BRAND, brand.id)
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.BRAND, brand.id)

        snapshots = await brand_snapshots(db_session, brand.id)
        assert len(snapshots) == 1
        assert snapshots[0].score == approx(0.4)


class TestBrandRollup:
    async def test_single_app_rollup_matches_app_snapshot(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="Humana")
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(db_session, name="App A", slug="app-a", org_unit_id=org_unit.id, brand_id=brand.id)

        app_snapshot = await _score_new_scan_run(
            db_session, app.id, [make_axe_payload(violations=[make_violation("r1", "serious")])]
        )
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.BRAND, brand.id)

        brand_snap = await latest_brand_snapshot(db_session, brand.id)
        assert brand_snap.score == approx(app_snapshot.score)
        assert brand_snap.total_violations == app_snapshot.total_violations
        assert brand_snap.total_pages == app_snapshot.total_pages
        assert brand_snap.pages_with_violations == app_snapshot.pages_with_violations
        assert brand_snap.pages_with_critical_violations == app_snapshot.pages_with_critical_violations

    async def test_two_apps_rollup_averages_scores_sums_counts(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="CenterWell")
        org_unit = await make_org_unit(db_session, name="Org")
        app_a = await make_app(db_session, name="App A", slug="app-a", org_unit_id=org_unit.id, brand_id=brand.id)
        app_b = await make_app(db_session, name="App B", slug="app-b", org_unit_id=org_unit.id, brand_id=brand.id)

        await _score_new_scan_run(
            db_session,
            app_a.id,
            [make_axe_payload(violations=[make_violation("r1", "serious")])],
            scanned_at=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
        )
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.BRAND, brand.id)
        await _score_new_scan_run(
            db_session,
            app_b.id,
            [make_axe_payload(url="https://example.com/b")],
            scanned_at=datetime(2026, 4, 1, 13, 0, 0, tzinfo=UTC),
        )
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.BRAND, brand.id)

        brand_snap = await latest_brand_snapshot(db_session, brand.id)
        assert brand_snap.score == approx(0.7)
        assert brand_snap.total_violations == 1
        assert brand_snap.total_pages == 2
        assert brand_snap.pages_with_violations == 1
        assert brand_snap.pages_with_critical_violations == 0

    async def test_apps_across_different_org_units(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="Go365")
        top = await make_org_unit(db_session, name="Top")
        ou_a = await make_org_unit(db_session, name="Division A", parent_id=top.id)
        ou_b = await make_org_unit(db_session, name="Division B", parent_id=top.id)
        app_a = await make_app(db_session, name="App A", slug="app-a", org_unit_id=ou_a.id, brand_id=brand.id)
        app_b = await make_app(db_session, name="App B", slug="app-b", org_unit_id=ou_b.id, brand_id=brand.id)

        await _score_new_scan_run(
            db_session,
            app_a.id,
            [make_axe_payload(violations=[make_violation("r1", "critical")])],
            scanned_at=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
        )
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.BRAND, brand.id)
        await _score_new_scan_run(
            db_session,
            app_b.id,
            [make_axe_payload(url="https://example.com/b")],
            scanned_at=datetime(2026, 4, 1, 13, 0, 0, tzinfo=UTC),
        )
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.BRAND, brand.id)

        brand_snap = await latest_brand_snapshot(db_session, brand.id)
        assert brand_snap.score == approx(0.5)
        assert brand_snap.total_violations == 1
        assert brand_snap.total_pages == 2
        assert brand_snap.pages_with_critical_violations == 1

    async def test_only_latest_app_snapshot_counts(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="Humana")
        org_unit = await make_org_unit(db_session, name="Org")
        app = await make_app(db_session, name="App", slug="app-latest", org_unit_id=org_unit.id, brand_id=brand.id)

        await _score_new_scan_run(
            db_session,
            app.id,
            [make_axe_payload(violations=[make_violation("r1", "critical")])],
            scanned_at=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
        )
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.BRAND, brand.id)
        await _score_new_scan_run(
            db_session,
            app.id,
            [make_axe_payload(url="https://example.com/b")],
            scanned_at=datetime(2026, 4, 1, 13, 0, 0, tzinfo=UTC),
        )
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.BRAND, brand.id)

        assert (await latest_brand_snapshot(db_session, brand.id)).score == approx(1.0)

    async def test_no_apps_with_scores_skips_snapshot(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session, name="CarePlus")
        org_unit = await make_org_unit(db_session, name="Org")
        await make_app(db_session, name="App", slug="app-no-scores", org_unit_id=org_unit.id, brand_id=brand.id)

        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.BRAND, brand.id)

        assert await brand_snapshots(db_session, brand.id) == []


def _bypass_dedupe_check_to_lose_the_race(mocker) -> None:
    # The race the constraint decides: the dedupe read saw nothing, but a
    # concurrent rollup's row lands before our write.
    mocker.patch.object(
        owner_service, "_snapshot_recorded_at_observation", new_callable=mocker.AsyncMock, return_value=None
    )


class TestRollupSnapshotUniqueness:
    async def test_schema_rejects_snapshot_with_two_owners(self, db_session: AsyncSession) -> None:
        # With the runtime exactly-one-owner guard gone, the check constraint is
        # the backstop; owned() can't even express this row, so build it raw.
        org_unit = await make_org_unit(db_session)
        brand = await make_brand(db_session)
        db_session.add(ScoreSnapshot(org_unit_id=org_unit.id, brand_id=brand.id, **SCORE_SNAPSHOT_DEFAULTS._asdict()))
        with pytest.raises(IntegrityError, match=CK_SCORE_SNAPSHOT_OWNER):
            await db_session.flush()

    async def test_schema_rejects_snapshot_with_no_owner(self, db_session: AsyncSession) -> None:
        # owned() can't express an ownerless row either — build it raw so the
        # constraint's zero-owner arm stays pinned alongside the two-owner arm.
        db_session.add(ScoreSnapshot(**SCORE_SNAPSHOT_DEFAULTS._asdict()))
        with pytest.raises(IntegrityError, match=CK_SCORE_SNAPSHOT_OWNER):
            await db_session.flush()

    async def test_schema_rejects_duplicate_org_unit_snapshot_at_one_observation_time(
        self, db_session: AsyncSession
    ) -> None:
        org_unit = await make_org_unit(db_session)
        await make_score_snapshot(db_session, org_unit_id=org_unit.id, snapshot_at=DEFAULT_SNAPSHOT_AT)
        db_session.add(build_score_snapshot(owner_type=ScoreSnapshotOwnerType.ORG_UNIT, owner_id=org_unit.id))
        with pytest.raises(IntegrityError, match=UQ_SCORE_SNAPSHOT_ORG_UNIT_SNAPSHOT_AT):
            await db_session.flush()

    async def test_schema_rejects_duplicate_brand_snapshot_at_one_observation_time(
        self, db_session: AsyncSession
    ) -> None:
        brand = await make_brand(db_session)
        await make_score_snapshot(db_session, brand_id=brand.id, snapshot_at=DEFAULT_SNAPSHOT_AT)
        db_session.add(build_score_snapshot(owner_type=ScoreSnapshotOwnerType.BRAND, owner_id=brand.id))
        with pytest.raises(IntegrityError, match=UQ_SCORE_SNAPSHOT_BRAND_SNAPSHOT_AT):
            await db_session.flush()

    async def test_app_snapshots_stay_unconstrained_per_observation_time(self, db_session: AsyncSession) -> None:
        # Two Scan Runs for one App may share scanned_at; latest selection
        # breaks the tie. Proven by the second flush not raising.
        app = await make_app_with_org_unit(db_session)
        first = await make_score_snapshot(db_session, app_id=app.id, snapshot_at=DEFAULT_SNAPSHOT_AT)
        second = await make_score_snapshot(db_session, app_id=app.id, snapshot_at=DEFAULT_SNAPSHOT_AT)
        assert first.id != second.id

    async def test_org_unit_rollup_losing_the_race_raises_concurrent_rollup_error(
        self, db_session: AsyncSession, mocker
    ) -> None:
        org_unit = await make_org_unit(db_session)
        app = await make_app(db_session, name="Race App", slug="race-app", org_unit_id=org_unit.id)
        await make_score_snapshot(db_session, app_id=app.id, snapshot_at=DEFAULT_SNAPSHOT_AT)
        # The winner's row: landed between our dedupe check and our write.
        await make_score_snapshot(db_session, org_unit_id=org_unit.id, snapshot_at=DEFAULT_SNAPSHOT_AT)
        _bypass_dedupe_check_to_lose_the_race(mocker)
        with pytest.raises(ConcurrentRollupError, match="Org unit.*updated by another request"):
            await owner_service.rollup(db_session, ScoreSnapshotOwnerType.ORG_UNIT, org_unit.id)

    async def test_brand_rollup_losing_the_race_raises_concurrent_rollup_error(
        self, db_session: AsyncSession, mocker
    ) -> None:
        brand = await make_brand(db_session)
        app = await make_app_with_org_unit(db_session, brand_id=brand.id)
        await make_score_snapshot(db_session, app_id=app.id, snapshot_at=DEFAULT_SNAPSHOT_AT)
        await make_score_snapshot(db_session, brand_id=brand.id, snapshot_at=DEFAULT_SNAPSHOT_AT)
        _bypass_dedupe_check_to_lose_the_race(mocker)
        with pytest.raises(ConcurrentRollupError, match="Brand.*updated by another request"):
            await owner_service.rollup(db_session, ScoreSnapshotOwnerType.BRAND, brand.id)


async def test_rollup_lock_non_deadlock_db_error_propagates_unchanged(db_session: AsyncSession, mocker) -> None:
    # Only a deadlock loss (40P01) translates to the retryable
    # ConcurrentRollupError; any other driver failure during lock acquisition
    # must surface unchanged (ADR 0028).
    org_unit = await make_org_unit(db_session, name="Org")
    err = DBAPIError("SELECT pg_advisory_xact_lock(...)", None, Exception("connection lost"))
    mocker.patch.object(db_session, "execute", new_callable=mocker.AsyncMock, side_effect=err)

    with pytest.raises(DBAPIError) as exc_info:
        await owner_service.rollup(db_session, ScoreSnapshotOwnerType.ORG_UNIT, org_unit.id)

    assert exc_info.value is err
