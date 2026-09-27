import re
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import ValidationError
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy.types import NullType

from a11y_health.core.pagination import (
    CursorPage,
    InvalidCursorError,
    KeysetMisconfigurationError,
    Page,
    PaginationParams,
    TotaledCursorPage,
    TotaledPage,
    encode_cursor,
    paginate,
)
from a11y_health.models.brand import Brand
from a11y_health.models.scan_run import ScanRun
from a11y_health.models.score_snapshot import ScoreSnapshot
from tests.factories import make_app_with_org_unit, make_brand, make_score_snapshot


async def test_paginate_single_keyset_first_page(db_session: AsyncSession) -> None:
    b1 = await make_brand(db_session, name="A")
    b2 = await make_brand(db_session, name="B")
    await make_brand(db_session, name="C")

    page = await paginate(db_session, select(Brand), keyset=[Brand.id], cursor=None, limit=2)

    assert [b.id for b in page.items] == [b1.id, b2.id]
    assert page.next_cursor is not None


async def test_paginate_single_keyset_second_page(db_session: AsyncSession) -> None:
    b1 = await make_brand(db_session, name="A")
    b2 = await make_brand(db_session, name="B")
    b3 = await make_brand(db_session, name="C")

    first = await paginate(db_session, select(Brand), keyset=[Brand.id], cursor=None, limit=2)
    second = await paginate(db_session, select(Brand), keyset=[Brand.id], cursor=first.next_cursor, limit=2)

    assert [b.id for b in second.items] == [b3.id]
    assert second.next_cursor is None
    first_ids = {b.id for b in first.items}
    assert first_ids == {b1.id, b2.id}
    assert first_ids.isdisjoint({b.id for b in second.items})


async def test_paginate_no_more_pages_at_exact_limit(db_session: AsyncSession) -> None:
    await make_brand(db_session, name="A")
    await make_brand(db_session, name="B")

    page = await paginate(db_session, select(Brand), keyset=[Brand.id], cursor=None, limit=2)

    assert len(page.items) == 2
    assert page.next_cursor is None


# Descending reads newest first, and its cursor continues into older rows
# (reversed comparison).
@pytest.mark.parametrize(
    ("descending", "first_page", "second_page"),
    [pytest.param(False, [0, 1], [2], id="ascending"), pytest.param(True, [2, 1], [0], id="descending")],
)
async def test_paginate_composite_keyset_round_trip(
    db_session: AsyncSession, descending: bool, first_page: list[int], second_page: list[int]
) -> None:
    brand = await make_brand(db_session)
    keyset = [ScoreSnapshot.snapshot_at, ScoreSnapshot.id]
    times = [datetime(2026, 1, day, tzinfo=UTC) for day in (1, 2, 3)]
    snaps = [await make_score_snapshot(db_session, brand_id=brand.id, snapshot_at=t) for t in times]

    stmt = select(ScoreSnapshot)
    first = await paginate(db_session, stmt, keyset=keyset, cursor=None, limit=2, descending=descending)
    second = await paginate(db_session, stmt, keyset=keyset, cursor=first.next_cursor, limit=2, descending=descending)

    assert [s.id for s in first.items] == [snaps[i].id for i in first_page]
    assert [s.id for s in second.items] == [snaps[i].id for i in second_page]
    assert second.next_cursor is None


@pytest.mark.parametrize(
    "bad_cursor",
    [
        "not-a-cursor",
        "",
        "A" * 5,  # not base64: 5 characters cannot encode whole bytes
        "A" * 513,  # over the decode length cap
        encode_cursor(1, 2),  # decodes cleanly but doesn't match the keyset width
    ],
)
async def test_paginate_rejects_invalid_cursor(db_session: AsyncSession, bad_cursor: str) -> None:
    with pytest.raises(InvalidCursorError):
        await paginate(db_session, select(Brand), keyset=[Brand.id], cursor=bad_cursor, limit=2)


# Validly encoded on both sides of the 512-character cap, so only the cap can
# refuse the longer one. 514 is the shortest valid encoding past 512.
async def test_paginate_accepts_a_cursor_at_the_length_cap(db_session: AsyncSession) -> None:
    cursor = encode_cursor("x" * 380)
    assert len(cursor) == 512

    page = await paginate(db_session, select(Brand), keyset=[Brand.name], cursor=cursor, limit=2)

    assert page.items == []


async def test_paginate_rejects_a_validly_encoded_cursor_over_the_length_cap(db_session: AsyncSession) -> None:
    cursor = encode_cursor("x" * 381)
    assert len(cursor) == 514

    with pytest.raises(InvalidCursorError):
        await paginate(db_session, select(Brand), keyset=[Brand.name], cursor=cursor, limit=2)


async def test_paginate_into_transforms_rows_and_keeps_cursor_from_row(db_session: AsyncSession) -> None:
    await make_brand(db_session, name="A")
    await make_brand(db_session, name="B")
    await make_brand(db_session, name="C")

    # into drops the id entirely — items are plain names, so paging can only
    # work if the cursor is recovered from the SQL row rather than the returned
    # item.
    stmt = select(Brand)
    into = lambda row: row[0].name  # noqa: E731
    first = await paginate(db_session, stmt, keyset=[Brand.id], cursor=None, limit=2, into=into)
    second = await paginate(db_session, stmt, keyset=[Brand.id], cursor=first.next_cursor, limit=2, into=into)

    assert first.items == ["A", "B"]
    assert first.next_cursor is not None
    assert second.items == ["C"]
    assert second.next_cursor is None


async def test_paginate_limit_zero_returns_empty_without_crashing(db_session: AsyncSession) -> None:
    await make_brand(db_session, name="A")
    await make_brand(db_session, name="B")

    page = await paginate(db_session, select(Brand), keyset=[Brand.id], cursor=None, limit=0)

    assert page.items == []
    assert page.next_cursor is None


@pytest.mark.parametrize(
    ("keyset", "bad_value"),
    [
        ([Brand.id], "not-an-int"),  # int column, non-numeric scalar -> ValueError
        ([ScoreSnapshot.snapshot_at, ScoreSnapshot.id], 12345),  # datetime column, numeric -> TypeError
        ([Brand.name], 123),  # str column, non-str scalar -> rejected before it reaches SQL
    ],
)
async def test_paginate_decodable_cursor_with_wrong_typed_value_is_rejected(
    db_session: AsyncSession, keyset: list, bad_value: int | str
) -> None:
    # Decodable but wrong-typed cursor must be a 400 (InvalidCursorError), not
    # a 500.
    cursor = encode_cursor(*([bad_value] + [1] * (len(keyset) - 1)))
    with pytest.raises(InvalidCursorError):
        await paginate(db_session, select(keyset[0].class_), keyset=keyset, cursor=cursor, limit=2)


_BRAND_ALIAS = aliased(Brand)
# A column type with no Python type (NullType, TSVECTOR, INET) makes
# `python_type` raise; no mapped column here has one, so a stand-in carries it.
_UNTYPED_COLUMN = SimpleNamespace(class_=Brand, key="untyped", type=NullType())


# The session has no `execute`, so reaching the first query fails with an
# AttributeError instead: raising the misconfiguration error proves the check
# ran before any round trip, on a first page with no cursor to decode.
@pytest.mark.parametrize(
    ("stmt", "keyset", "column"),
    [
        pytest.param(select(ScanRun), [ScanRun.status], "ScanRun.status", id="unsupported-type"),
        pytest.param(select(Brand.id, Brand.name), [Brand.id], "Brand.id", id="bare-scalar"),
        pytest.param(select(Brand), [ScoreSnapshot.id], "ScoreSnapshot.id", id="entity-not-selected"),
        pytest.param(select(_BRAND_ALIAS), [Brand.id], "Brand.id", id="only-an-alias-selected"),
        pytest.param(select(Brand), [_UNTYPED_COLUMN], "Brand.untyped", id="no-python-type"),
    ],
)
async def test_paginate_refuses_a_misconfigured_keyset_before_the_first_query(
    stmt: Select, keyset: list, column: str
) -> None:
    no_session = cast("AsyncSession", object())

    with pytest.raises(KeysetMisconfigurationError, match=rf"^keyset column {re.escape(column)}:"):
        await paginate(no_session, stmt, keyset=keyset, cursor=None, limit=2)


async def test_paginate_keyset_on_a_selected_alias_round_trip(db_session: AsyncSession) -> None:
    for name in ("A", "B", "C"):
        await make_brand(db_session, name=name)

    stmt = select(_BRAND_ALIAS)
    first = await paginate(db_session, stmt, keyset=[_BRAND_ALIAS.id], cursor=None, limit=2)
    second = await paginate(db_session, stmt, keyset=[_BRAND_ALIAS.id], cursor=first.next_cursor, limit=2)

    assert [b.name for b in first.items] == ["A", "B"]
    assert [b.name for b in second.items] == ["C"]


async def test_paginate_composite_keyset_breaks_ties_on_id(db_session: AsyncSession) -> None:
    # App-owned snapshots: the one owner where equal snapshot_at rows are legal
    # (rollup owners are unique per observation time since #98).
    app = await make_app_with_org_unit(db_session)
    keyset = [ScoreSnapshot.snapshot_at, ScoreSnapshot.id]
    tied = datetime(2026, 1, 1, tzinfo=UTC)
    snaps = [await make_score_snapshot(db_session, app_id=app.id, snapshot_at=tied) for _ in range(3)]
    ordered = sorted(s.id for s in snaps)

    stmt = select(ScoreSnapshot)
    first = await paginate(db_session, stmt, keyset=keyset, cursor=None, limit=2)
    second = await paginate(db_session, stmt, keyset=keyset, cursor=first.next_cursor, limit=2)

    assert [s.id for s in first.items] == ordered[:2]
    assert [s.id for s in second.items] == ordered[2:]
    assert second.next_cursor is None


async def test_paginate_into_over_aggregate_row_recovers_cursor_past_scalars(db_session: AsyncSession) -> None:
    # Aggregate row (scalar, Entity): the cursor must be recovered from the
    # entity's position past the scalar, which a row leading with the entity
    # (every production caller's shape) can't regress.
    for name in ("A", "B", "C"):
        await make_brand(db_session, name=name)

    stmt = select(func.length(Brand.name).label("name_len"), Brand)
    into = lambda r: (r.Brand.name, r.name_len)  # noqa: E731
    first = await paginate(db_session, stmt, keyset=[Brand.id], cursor=None, limit=2, into=into)
    second = await paginate(db_session, stmt, keyset=[Brand.id], cursor=first.next_cursor, limit=2, into=into)

    assert first.items == [("A", 1), ("B", 1)]
    assert first.next_cursor is not None
    assert second.items == [("C", 1)]
    assert second.next_cursor is None


async def test_paginate_string_keyset_round_trip(db_session: AsyncSession) -> None:
    for name in ("alpha", "bravo", "charlie"):
        await make_brand(db_session, name=name)

    keyset = [Brand.name]
    stmt = select(Brand)
    first = await paginate(db_session, stmt, keyset=keyset, cursor=None, limit=2)
    second = await paginate(db_session, stmt, keyset=keyset, cursor=first.next_cursor, limit=2)

    assert [b.name for b in first.items] == ["alpha", "bravo"]
    assert [b.name for b in second.items] == ["charlie"]
    assert second.next_cursor is None


async def test_paginate_with_total_counts_beyond_the_page(db_session: AsyncSession) -> None:
    for name in ("alpha", "bravo", "charlie"):
        await make_brand(db_session, name=name)

    page = await paginate(db_session, select(Brand), keyset=[Brand.id], cursor=None, limit=2, with_total=True)

    assert isinstance(page, TotaledCursorPage)
    assert len(page.items) == 2
    assert page.next_cursor is not None
    assert page.total == 3


async def test_paginate_with_total_keeps_the_full_count_on_a_later_page(db_session: AsyncSession) -> None:
    for name in ("alpha", "bravo", "charlie"):
        await make_brand(db_session, name=name)

    stmt = select(Brand)
    first = await paginate(db_session, stmt, keyset=[Brand.id], cursor=None, limit=2, with_total=True)
    second = await paginate(db_session, stmt, keyset=[Brand.id], cursor=first.next_cursor, limit=2, with_total=True)

    assert len(second.items) == 1
    assert second.total == 3


async def test_paginate_with_total_when_the_first_page_is_the_last(db_session: AsyncSession) -> None:
    for name in ("alpha", "bravo"):
        await make_brand(db_session, name=name)

    page = await paginate(db_session, select(Brand), keyset=[Brand.id], cursor=None, limit=5, with_total=True)

    assert page.next_cursor is None
    assert page.total == 2


# Expected values are the published contract (Story #80): default page size 20,
# bounds 1..100 — literals here, so a drift in the module is caught, not
# mirrored.
class TestPaginationParams:
    def test_defaults_to_no_cursor_and_page_size_twenty(self) -> None:
        params = PaginationParams()
        assert params.cursor is None
        assert params.limit == 20

    @pytest.mark.parametrize("limit", [0, 101, -1])
    def test_out_of_bounds_page_size_is_rejected(self, limit: int) -> None:
        with pytest.raises(ValidationError):
            PaginationParams(limit=limit)

    @pytest.mark.parametrize("limit", [1, 100])
    def test_bounds_are_inclusive(self, limit: int) -> None:
        assert PaginationParams(limit=limit).limit == limit


class TestPageFromCursorPage:
    def test_maps_items_and_preserves_cursor(self) -> None:
        internal = CursorPage(items=[1, 2, 3], next_cursor="cursor-xyz")

        page = Page.from_cursor_page(internal, str)

        assert page.items == ["1", "2", "3"]
        assert page.next_cursor == "cursor-xyz"

    def test_default_mapper_passes_items_through_unchanged(self) -> None:
        internal = CursorPage(items=["already", "shaped"], next_cursor="c1")

        page = Page.from_cursor_page(internal)

        assert page.items == ["already", "shaped"]
        assert page.next_cursor == "c1"

    def test_empty_result_yields_no_items_and_no_cursor(self) -> None:
        internal: CursorPage[int] = CursorPage(items=[], next_cursor=None)

        page = Page.from_cursor_page(internal, str)

        assert page.items == []
        assert page.next_cursor is None

    def test_absent_cursor_stays_absent(self) -> None:
        internal = CursorPage(items=[1], next_cursor=None)

        page = Page.from_cursor_page(internal, str)

        assert page.next_cursor is None


class TestTotaledPageFromTotaledCursorPage:
    # Pins the type-level guard: as a subclass, a totaled page would type-check
    # into `Page.from_cursor_page` and lose `total` without a runtime error.
    def test_a_totaled_cursor_page_is_not_a_cursor_page(self) -> None:
        assert not issubclass(TotaledCursorPage, CursorPage)

    def test_preserves_items_cursor_and_total(self) -> None:
        internal = TotaledCursorPage(items=["already", "shaped"], next_cursor="cursor-xyz", total=7)

        page = TotaledPage.from_totaled_cursor_page(internal)

        assert page.items == ["already", "shaped"]
        assert page.next_cursor == "cursor-xyz"
        assert page.total == 7

    def test_empty_result_yields_no_items_and_zero_total(self) -> None:
        internal: TotaledCursorPage[int] = TotaledCursorPage(items=[], next_cursor=None, total=0)

        page = TotaledPage.from_totaled_cursor_page(internal)

        assert page.items == []
        assert page.next_cursor is None
        assert page.total == 0
