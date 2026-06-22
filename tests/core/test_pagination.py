from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.pagination import CursorPage, InvalidCursorError, Page, encode_cursor, paginate
from a11y_health.models.brand import Brand
from a11y_health.models.score_snapshot import ScoreSnapshot
from tests.factories import make_brand, make_score_snapshot


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


async def test_paginate_composite_keyset_round_trip(db_session: AsyncSession) -> None:
    brand = await make_brand(db_session)
    keyset = [ScoreSnapshot.snapshot_at, ScoreSnapshot.id]
    times = [datetime(2026, 1, day, tzinfo=UTC) for day in (1, 2, 3)]
    snaps = [await make_score_snapshot(db_session, brand_id=brand.id, snapshot_at=t) for t in times]

    stmt = select(ScoreSnapshot)
    first = await paginate(db_session, stmt, keyset=keyset, cursor=None, limit=2)
    second = await paginate(db_session, stmt, keyset=keyset, cursor=first.next_cursor, limit=2)

    assert [s.id for s in first.items] == [snaps[0].id, snaps[1].id]
    assert [s.id for s in second.items] == [snaps[2].id]
    assert second.next_cursor is None


@pytest.mark.parametrize("bad_cursor", ["not-a-cursor", ""])
async def test_paginate_rejects_invalid_cursor(db_session: AsyncSession, bad_cursor: str) -> None:
    with pytest.raises(InvalidCursorError):
        await paginate(db_session, select(Brand), keyset=[Brand.id], cursor=bad_cursor, limit=2)


async def test_paginate_into_transforms_rows_and_keeps_cursor_from_row(db_session: AsyncSession) -> None:
    await make_brand(db_session, name="A")
    await make_brand(db_session, name="B")
    await make_brand(db_session, name="C")

    # into drops the id entirely — items are plain names, so paging can only work
    # if the cursor is recovered from the SQL row rather than the returned item.
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
    # Decodable but wrong-typed cursor must be a 400 (InvalidCursorError), not a 500.
    cursor = encode_cursor(*([bad_value] + [1] * (len(keyset) - 1)))
    with pytest.raises(InvalidCursorError):
        await paginate(db_session, select(Brand), keyset=keyset, cursor=cursor, limit=2)


async def test_paginate_composite_keyset_breaks_ties_on_id(db_session: AsyncSession) -> None:
    brand = await make_brand(db_session)
    keyset = [ScoreSnapshot.snapshot_at, ScoreSnapshot.id]
    tied = datetime(2026, 1, 1, tzinfo=UTC)
    snaps = [await make_score_snapshot(db_session, brand_id=brand.id, snapshot_at=tied) for _ in range(3)]
    ordered = sorted(s.id for s in snaps)

    stmt = select(ScoreSnapshot)
    first = await paginate(db_session, stmt, keyset=keyset, cursor=None, limit=2)
    second = await paginate(db_session, stmt, keyset=keyset, cursor=first.next_cursor, limit=2)

    assert [s.id for s in first.items] == ordered[:2]
    assert [s.id for s in second.items] == ordered[2:]
    assert second.next_cursor is None


async def test_paginate_into_over_aggregate_row_recovers_cursor_past_scalars(db_session: AsyncSession) -> None:
    # Aggregate row (Entity, scalar, ...): the cursor must be recovered past the
    # scalars — a select(Entity)-only test can't regress that path.
    for name in ("A", "B", "C"):
        await make_brand(db_session, name=name)

    stmt = select(Brand, func.length(Brand.name).label("name_len"))
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


def _to_str(n: int) -> str:
    return str(n)


class TestPageFromCursorPage:
    def test_maps_items_and_preserves_cursor(self) -> None:
        internal = CursorPage(items=[1, 2, 3], next_cursor="cursor-xyz")

        page = Page.from_cursor_page(internal, _to_str)

        assert page.items == ["1", "2", "3"]
        assert page.next_cursor == "cursor-xyz"

    def test_default_mapper_passes_items_through_unchanged(self) -> None:
        internal = CursorPage(items=["already", "shaped"], next_cursor="c1")

        page = Page.from_cursor_page(internal)

        assert page.items == ["already", "shaped"]
        assert page.next_cursor == "c1"

    def test_empty_result_yields_no_items_and_no_cursor(self) -> None:
        internal: CursorPage[int] = CursorPage(items=[], next_cursor=None)

        page = Page.from_cursor_page(internal, _to_str)

        assert page.items == []
        assert page.next_cursor is None

    def test_absent_cursor_stays_absent(self) -> None:
        internal = CursorPage(items=[1], next_cursor=None)

        page = Page.from_cursor_page(internal, _to_str)

        assert page.next_cursor is None
