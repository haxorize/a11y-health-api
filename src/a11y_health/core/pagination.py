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
from typing import Annotated, Literal, cast, overload

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


# Deliberately not an InvalidCursorError: a bad keyset type is a server-side
# misconfiguration, so it should 500 in development, not be masked as a 400.
class UnsupportedKeysetTypeError(Exception):
    def __init__(self, python_type: type) -> None:
        super().__init__(f"Unsupported keyset column type: {python_type.__name__}")


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


# The one request-facing declaration of pagination: endpoints take a single
# `PageParams` argument and FastAPI surfaces it as the flat `cursor`/`limit`
# query parameters, so bounds and default live only here. Depends(), not
# Query(): a Query() parameter model silently stops flattening when the
# endpoint declares any other query parameter (all FastAPI versions through
# 0.139), while a model dependency composes with them.
PageParams = Annotated[PaginationParams, Depends()]


@dataclass(frozen=True)
class CursorPage[T]:
    items: list[T]
    next_cursor: str | None


@dataclass(frozen=True)
class TotaledCursorPage[T](CursorPage[T]):
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
        if isinstance(page, TotaledCursorPage):
            # A totaled page reaching the plain converter means the count query
            # was paid and its result silently dropped — fail loud instead.
            raise TypeError("page carries a total — serve it via TotaledPage.from_totaled_cursor_page")
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


# Each keyset column's entity must be present in the row as an ORM instance
# (true for select(Entity) and select(Entity, agg, ...)); a bare scalar keyset
# column has no entity to read and raises below rather than mis-paging.
def _cursor_values(row: Row, keyset: Sequence[InstrumentedAttribute]) -> list:
    values = []
    for attr in keyset:
        entity = next((v for v in row if isinstance(v, cast("type", attr.class_))), None)
        if entity is None:
            raise LookupError(f"keyset column {attr.key!r}: no {attr.class_.__name__} instance in result row")
        values.append(getattr(entity, attr.key))
    return values


def _coerce(attr: InstrumentedAttribute, raw: object) -> object:
    python_type = attr.type.python_type
    if python_type is datetime:
        return datetime.fromisoformat(cast("str", raw))
    if python_type is int:
        return int(cast("str | int", raw))
    if python_type is str:
        if not isinstance(raw, str):
            raise InvalidCursorError
        return raw
    raise UnsupportedKeysetTypeError(python_type)


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
) -> CursorPage[T]:
    """Apply keyset pagination to `stmt`, returning a page and the next cursor.

    `descending` reverses both the ORDER BY and the keyset comparison so paging
    walks newest→oldest; cursor encoding stays direction-agnostic.

    `with_total=True` also serves the full filtered count as a
    `TotaledCursorPage` — counted from the same statement the page runs over,
    so the two can never disagree on which rows are in scope. The count is a
    second query, so under READ COMMITTED a commit landing between the two can
    make `total` lag the page by the concurrent writes; a refetch corrects it.

    Caller contract not captured by the types:
    - `keyset` columns must be NOT NULL — a NULL makes the row-value `>`
      comparison return NULL and silently drops rows. Use primary keys or NOT
      NULL columns.
    - each keyset column's owning entity must appear in the result row (true
      for `select(Entity)` and `select(Entity, agg, ...)`); a bare scalar
      keyset column raises rather than mis-paging.

    Raises `InvalidCursorError` on a malformed cursor (handled as 400) and
    `UnsupportedKeysetTypeError` if a keyset column's type isn't
    int/datetime/str.
    """
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
    next_cursor = encode_cursor(*_cursor_values(page_rows[-1], keyset)) if has_more and page_rows else None
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
