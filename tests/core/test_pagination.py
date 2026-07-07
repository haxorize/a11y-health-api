from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.routing import iter_route_contexts
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.error_contract import ErrorCode
from a11y_health.core.pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    CursorPage,
    InvalidCursorError,
    Page,
    PaginationParams,
    encode_cursor,
    paginate,
)
from a11y_health.main import app
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


async def test_paginate_descending_composite_keyset_round_trip(db_session: AsyncSession) -> None:
    brand = await make_brand(db_session)
    keyset = [ScoreSnapshot.snapshot_at, ScoreSnapshot.id]
    times = [datetime(2026, 1, day, tzinfo=UTC) for day in (1, 2, 3)]
    snaps = [await make_score_snapshot(db_session, brand_id=brand.id, snapshot_at=t) for t in times]

    stmt = select(ScoreSnapshot)
    first = await paginate(db_session, stmt, keyset=keyset, cursor=None, limit=2, descending=True)
    second = await paginate(db_session, stmt, keyset=keyset, cursor=first.next_cursor, limit=2, descending=True)

    # Newest first, and the cursor continues into older rows (reversed comparison).
    assert [s.id for s in first.items] == [snaps[2].id, snaps[1].id]
    assert [s.id for s in second.items] == [snaps[0].id]
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


def _flat_dependants(dependant: Any) -> Iterator[Any]:
    yield dependant
    for sub in dependant.dependencies:
        yield from _flat_dependants(sub)


# An operation "accepts a cursor" whether the parameter arrives hand-rolled on
# the endpoint or through any dependency — both shapes are swept, so a
# hand-rolled regression is still caught. iter_route_contexts is the traversal
# FastAPI's own OpenAPI generation walks, so the sweep sees every served
# operation, not just one router's.
def _accepts_cursor(dependant: Any) -> bool:
    return any(field.name == "cursor" for dep in _flat_dependants(dependant) for field in dep.query_params)


def _cursor_operations() -> list[Any]:
    operations = [
        ctx
        for ctx in iter_route_contexts(app.routes)
        # docs/spec routes are plain starlette Routes with no dependant to sweep
        if getattr(ctx, "dependant", None) is not None and _accepts_cursor(ctx.dependant)
    ]
    assert operations, "cursor-operation sweep found nothing — detection is broken"
    return operations


def test_every_cursor_operation_uses_the_pagination_owned_definition() -> None:
    for op in _cursor_operations():
        own_params = {field.name for field in op.dependant.query_params}
        assert "cursor" not in own_params and "limit" not in own_params, (
            f"{sorted(op.methods)} {op.path_format} re-declares pagination parameters "
            f"locally — consume PageParams from core.pagination instead"
        )
        assert any(dep.call is PaginationParams for dep in _flat_dependants(op.dependant)), (
            f"{sorted(op.methods)} {op.path_format} accepts a cursor but not via PageParams from core.pagination"
        )


def test_every_cursor_operation_declares_the_invalid_cursor_mode() -> None:
    for op in _cursor_operations():
        declared_codes = {code for entry in op.responses.values() for code in entry.get("x-error-codes", [])}
        assert ErrorCode.INVALID_CURSOR in declared_codes, (
            f"{sorted(op.methods)} {op.path_format} accepts a cursor but does not declare "
            f"the invalid-cursor error mode — add ErrorCode.INVALID_CURSOR to its error_responses()"
        )


def test_openapi_page_size_bounds_and_default_propagate_from_the_module() -> None:
    spec = app.openapi()
    for op in _cursor_operations():
        for method in op.methods:
            params = {p["name"]: p for p in spec["paths"][op.path_format][method.lower()]["parameters"]}
            limit_schema = params["limit"]["schema"]
            assert limit_schema["minimum"] == 1, f"{method} {op.path_format}"
            assert limit_schema["maximum"] == MAX_PAGE_SIZE, f"{method} {op.path_format}"
            assert limit_schema["default"] == DEFAULT_PAGE_SIZE, f"{method} {op.path_format}"


# Expected values are the published contract (Story #80): default page size 20,
# bounds 1..100 — literals here, so a drift in the module is caught, not mirrored.
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
