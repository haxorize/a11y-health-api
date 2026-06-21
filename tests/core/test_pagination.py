from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.pagination import InvalidCursorError, paginate
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
