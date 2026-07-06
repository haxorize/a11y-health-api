"""Keyset (cursor) pagination shared by every list endpoint.

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
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, cast, overload

from fastapi import Depends
from pydantic import BaseModel, Field
from sqlalchemy import Row, Select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from a11y_health.core.exceptions import DomainError


class InvalidCursorError(DomainError):
    def __init__(self) -> None:
        super().__init__("Invalid cursor")


# Deliberately not an InvalidCursorError: a bad keyset type is a server-side
# misconfiguration, so it should 500 in development, not be masked as a 400.
class UnsupportedKeysetTypeError(Exception):
    def __init__(self, python_type: type) -> None:
        super().__init__(f"Unsupported keyset column type: {python_type.__name__}")


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


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None

    # `item` is omitted only where the internal items are already the public type —
    # an `into` aggregate returning the Read model itself (e.g. PageMetricsRead).
    @overload
    @classmethod
    def from_cursor_page[I](cls, page: CursorPage[I]) -> "Page[I]": ...
    @overload
    @classmethod
    def from_cursor_page[I, R](cls, page: CursorPage[I], item: Callable[[I], R]) -> "Page[R]": ...
    @classmethod
    def from_cursor_page[I, R](cls, page: CursorPage[I], item: Callable[[I], R] | None = None) -> "Page[I] | Page[R]":
        if item is None:
            return Page(items=page.items, next_cursor=page.next_cursor)
        return Page(items=[item(i) for i in page.items], next_cursor=page.next_cursor)


def encode_cursor(*values: int | str | datetime) -> str:
    payload = [v.isoformat() if isinstance(v, datetime) else v for v in values]
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    return raw.rstrip("=")


def decode_cursor(cursor: str, *, expected: int) -> list:
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


async def paginate[T](
    session: AsyncSession,
    stmt: Select,
    *,
    keyset: Sequence[InstrumentedAttribute],
    cursor: str | None,
    limit: int,
    into: Callable[[Row], T] | None = None,
) -> CursorPage[T]:
    """Apply keyset pagination to `stmt`, returning one page and the next cursor.

    Caller contract not captured by the types:
    - `keyset` columns must be NOT NULL — a NULL makes the row-value `>` comparison
      return NULL and silently drops rows. Use primary keys or NOT NULL columns.
    - each keyset column's owning entity must appear in the result row (true for
      `select(Entity)` and `select(Entity, agg, ...)`); a bare scalar keyset column
      raises rather than mis-paging.

    Raises `InvalidCursorError` on a malformed cursor (handled as 400) and
    `UnsupportedKeysetTypeError` if a keyset column's type isn't int/datetime/str.
    """
    if cursor is not None:
        decoded = decode_cursor(cursor, expected=len(keyset))
        try:
            bound = tuple(_coerce(attr, raw) for attr, raw in zip(keyset, decoded, strict=True))
        except (ValueError, TypeError) as exc:
            raise InvalidCursorError from exc
        stmt = stmt.where(tuple_(*keyset) > bound)
    stmt = stmt.order_by(*keyset).limit(limit + 1)
    rows = (await session.execute(stmt)).all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    items = [into(row) if into is not None else row[0] for row in page_rows]
    next_cursor = encode_cursor(*_cursor_values(page_rows[-1], keyset)) if has_more and page_rows else None
    return CursorPage(items=items, next_cursor=next_cursor)
