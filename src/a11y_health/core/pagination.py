"""Cursor Pagination (keyset) shared by every unbounded list endpoint.

The module owns both halves of pagination. `PageParams` is the one
request-facing declaration — endpoints consume it instead of hand-rolling
`cursor`/`limit`, so page-size bounds and the default live only here.
`paginate()` is the single deep query entry point: callers hand it a filtered
query and the keyset columns, and it owns cursor decode/encode, ordering, the
`limit + 1` has-more probe, and slicing. No list service rolls its own paging.

See `docs/architecture.md` ("Pagination") for the model and
`docs/adr/0017-keyset-pagination-deep-module.md` for why it's one module.
"""

import base64
import enum
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Literal, overload

from fastapi import Depends
from pydantic import BaseModel, Field
from sqlalchemy import Row, Select, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from a11y_health.core.exceptions import DomainError


class InvalidCursorError(DomainError):
    """The pagination module's own contribution to the domain error set.

    Defined here rather than in `core/exceptions.py`, so a reader greping that
    module for the full set of `DomainError` subclasses will not find this one.
    """

    def __init__(self) -> None:
        super().__init__("Invalid cursor")


# Deliberately not an InvalidCursorError: a bad keyset is a server-side
# misconfiguration, so it should 500 in development, not be masked as a 400.
class KeysetMisconfigurationError(Exception):
    def __init__(self, attr: InstrumentedAttribute, problem: str) -> None:
        super().__init__(f"keyset column {attr.class_.__name__}.{attr.key}: {problem}")


# Sort Order (DOMAIN.md): the request-facing vocabulary for listings that let
# the client choose paging direction. Most listings bake their direction
# per-operation instead (ADR 0017); an endpoint exposes this only when both
# directions have real consumers.
class SortOrder(enum.StrEnum):
    ASC = "asc"
    DESC = "desc"

    @property
    def descending(self) -> bool:
        return self is SortOrder.DESC


def _order_query(order: SortOrder = SortOrder.ASC) -> SortOrder:
    return order


# The shared declaration of the `order` query parameter, like `PageParams` for
# `cursor`/`limit`: opt-in per endpoint, but the default lives only here.
OrderParam = Annotated[SortOrder, Depends(_order_query)]


_MAX_CURSOR_LENGTH = 512

DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100


class PaginationParams(BaseModel):
    cursor: str | None = None
    limit: int = Field(DEFAULT_PAGE_SIZE, ge=1, le=MAX_PAGE_SIZE)


# Depends(), not Query(): a Query() parameter model silently stops flattening
# when the endpoint declares any other query parameter (all FastAPI versions
# through 0.139), while a model dependency composes with them.
PageParams = Annotated[PaginationParams, Depends()]


@dataclass(frozen=True)
class CursorPage[T]:
    items: list[T]
    next_cursor: str | None


# Not a CursorPage subclass: a totaled page reaching `Page.from_cursor_page`
# would pay the count query and drop `total`, and without the subtype that
# mis-call is a type error rather than a runtime one.
@dataclass(frozen=True)
class TotaledCursorPage[T]:
    items: list[T]
    next_cursor: str | None
    total: int


# The pagination response envelope: one page of a listing as served, not the
# domain's Page Result or Page Health. `CursorPage` is its service-layer twin,
# which `from_cursor_page` converts into this; a page carrying a total goes
# through `TotaledPage` instead.
class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None

    # `item` is omitted only where the internal items are already the public
    # type — an `into` aggregate returning the Read model itself (e.g.
    # PageMetricsRead).
    @overload
    @classmethod
    def from_cursor_page[I](cls, page: CursorPage[I]) -> Page[I]: ...
    @overload
    @classmethod
    def from_cursor_page[I, R](cls, page: CursorPage[I], item: Callable[[I], R]) -> Page[R]: ...
    @classmethod
    def from_cursor_page[I, R](cls, page: CursorPage[I], item: Callable[[I], R] | None = None) -> Page[I] | Page[R]:
        if item is None:
            return Page(items=page.items, next_cursor=page.next_cursor)
        return Page(items=[item(i) for i in page.items], next_cursor=page.next_cursor)


# Per-operation extension, not a field on Page: only operations whose consumers
# need an exact filtered count pay the count query, and every other envelope
# keeps its two-field shape.
class TotaledPage[T](Page[T]):
    total: int

    @overload
    @classmethod
    def from_totaled_cursor_page[I](cls, page: TotaledCursorPage[I]) -> TotaledPage[I]: ...
    @overload
    @classmethod
    def from_totaled_cursor_page[I, R](cls, page: TotaledCursorPage[I], item: Callable[[I], R]) -> TotaledPage[R]: ...
    @classmethod
    def from_totaled_cursor_page[I, R](
        cls, page: TotaledCursorPage[I], item: Callable[[I], R] | None = None
    ) -> TotaledPage[I] | TotaledPage[R]:
        if item is None:
            return TotaledPage(items=page.items, next_cursor=page.next_cursor, total=page.total)
        return TotaledPage(items=[item(i) for i in page.items], next_cursor=page.next_cursor, total=page.total)


def encode_cursor(*values: int | str | datetime) -> str:
    jsonable = [v.isoformat() if isinstance(v, datetime) else v for v in values]
    raw = base64.urlsafe_b64encode(json.dumps(jsonable).encode()).decode()
    return raw.rstrip("=")


def _decode_cursor(cursor: str, *, expected: int) -> list:
    if len(cursor) > _MAX_CURSOR_LENGTH:
        raise InvalidCursorError
    try:
        pad = "=" * (-len(cursor) % 4)
        decoded = json.loads(base64.urlsafe_b64decode((cursor + pad).encode()))
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidCursorError from exc
    if not isinstance(decoded, list) or len(decoded) != expected:
        raise InvalidCursorError
    return decoded


def _require_str(raw: object) -> str:
    if not isinstance(raw, str):
        raise InvalidCursorError
    return raw


# The supported keyset types, each with its cursor decoding: one table, so the
# entry check and the coercion cannot disagree on what is supported.
_KEYSET_COERCIONS: dict[type, Callable[[Any], object]] = {
    int: int,
    datetime: datetime.fromisoformat,
    str: _require_str,
}


def _keyset_type(attr: InstrumentedAttribute) -> type:
    try:
        python_type = attr.type.python_type
    except NotImplementedError:
        raise KeysetMisconfigurationError(attr, f"unsupported type {attr.type!r}") from None
    if python_type not in _KEYSET_COERCIONS:
        raise KeysetMisconfigurationError(attr, f"unsupported type {python_type.__name__}")
    return python_type


# A scalar column's description names an entity too, so only a description
# whose type is a class is a selected entity. An alias matches itself alone:
# `Brand.id` must not read its cursor from an `aliased(Brand)` row.
def _selects(description: dict[str, Any], owner: object) -> bool:
    if not isinstance(description["type"], type):
        return False
    entity = description["entity"]
    if isinstance(entity, type) and isinstance(owner, type):
        return issubclass(entity, owner)
    return entity is owner


# The row position each keyset column's cursor value is read back from: the
# first selected entity the column belongs to. Checks the column's type on the
# way, so both preconditions fail before the first query.
def _keyset_positions(stmt: Select, keyset: Sequence[InstrumentedAttribute]) -> list[int]:
    descriptions = stmt.column_descriptions
    positions = []
    for attr in keyset:
        _keyset_type(attr)
        owner = attr.class_
        position = next((i for i, d in enumerate(descriptions) if _selects(d, owner)), None)
        if position is None:
            raise KeysetMisconfigurationError(attr, f"no {owner.__name__} entity among the selected columns")
        positions.append(position)
    return positions


def _coerce(attr: InstrumentedAttribute, raw: object) -> object:
    return _KEYSET_COERCIONS[attr.type.python_type](raw)


@overload
async def paginate[T](
    session: AsyncSession,
    stmt: Select,
    *,
    keyset: Sequence[InstrumentedAttribute],
    cursor: str | None,
    limit: int,
    descending: bool = ...,
    into: Callable[[Row], T] | None = ...,
    with_total: Literal[False] = ...,
) -> CursorPage[T]: ...
@overload
async def paginate[T](
    session: AsyncSession,
    stmt: Select,
    *,
    keyset: Sequence[InstrumentedAttribute],
    cursor: str | None,
    limit: int,
    descending: bool = ...,
    into: Callable[[Row], T] | None = ...,
    with_total: Literal[True],
) -> TotaledCursorPage[T]: ...
async def paginate[T](
    session: AsyncSession,
    stmt: Select,
    *,
    keyset: Sequence[InstrumentedAttribute],
    cursor: str | None,
    limit: int,
    descending: bool = False,
    into: Callable[[Row], T] | None = None,
    with_total: bool = False,
) -> CursorPage[T] | TotaledCursorPage[T]:
    """Apply keyset pagination to `stmt`, returning a page and the next cursor.

    `descending` reverses both the ORDER BY and the keyset comparison so paging
    walks newest→oldest; cursor encoding stays direction-agnostic.

    `with_total=True` also serves the full filtered count as a
    `TotaledCursorPage` — counted from the same statement the page runs over,
    so the two can never disagree on which rows are in scope. The count is a
    second query, so under READ COMMITTED a commit landing between the two can
    make `total` lag the page by the concurrent writes; a refetch corrects it.

    Caller contract not captured by the types: no NULL may reach a keyset
    column of the paged rows. A NULL makes the row-value `>` comparison return
    NULL and silently drops rows. Declaring the column NOT NULL is one way;
    filtering the NULLs out is the other, which is how `list_latest_scores`
    pages a nullable owner column. That second way is why this is not checked
    at entry (ADR 0017).

    Raises `InvalidCursorError` on a malformed cursor (handled as 400) and,
    before any query, `KeysetMisconfigurationError` if a keyset column's type
    isn't int/datetime/str or its entity is not in the result row, as it is
    for `select(Entity)` and `select(Entity, agg, ...)`.
    """
    positions = _keyset_positions(stmt, keyset)
    unpaged = stmt
    order = [col.desc() for col in keyset] if descending else list(keyset)
    if cursor is not None:
        decoded = _decode_cursor(cursor, expected=len(keyset))
        try:
            bound = tuple(_coerce(attr, raw) for attr, raw in zip(keyset, decoded, strict=True))
        except (ValueError, TypeError) as exc:
            raise InvalidCursorError from exc
        keys = tuple_(*keyset)
        stmt = stmt.where(keys < bound if descending else keys > bound)
    stmt = stmt.order_by(*order).limit(limit + 1)
    rows = (await session.execute(stmt)).all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    items = [into(row) if into is not None else row[0] for row in page_rows]
    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = encode_cursor(*(getattr(last[i], attr.key) for attr, i in zip(keyset, positions, strict=True)))
    if not with_total:
        return CursorPage(items=items, next_cursor=next_cursor)
    if cursor is None and not has_more:
        total = len(items)  # the first page is also the last — no count query needed
    else:
        # Counted over the pre-cursor statement so later pages still report the
        # full set. Postgres prunes the derived table's unreferenced output
        # columns (e.g. a correlated per-row aggregate), so the count pays for
        # the filtered row scan only, not the page's SELECT-list work.
        count_stmt = select(func.count()).select_from(unpaged.order_by(None).subquery())
        total = (await session.execute(count_stmt)).scalar_one()
    return TotaledCursorPage(items=items, next_cursor=next_cursor, total=total)
