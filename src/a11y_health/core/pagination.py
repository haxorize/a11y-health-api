import base64
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import cast

from pydantic import BaseModel
from sqlalchemy import Row, Select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute


class InvalidCursorError(Exception):
    def __init__(self) -> None:
        super().__init__("Invalid cursor")


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


@dataclass(frozen=True)
class CursorPage[T]:
    items: list[T]
    next_cursor: str | None


def encode_cursor(*values: int | str | datetime) -> str:
    payload = [v.isoformat() if isinstance(v, datetime) else v for v in values]
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    return raw.rstrip("=")


def decode_cursor(cursor: str, *, expected: int) -> list:
    try:
        pad = "=" * (-len(cursor) % 4)
        decoded = json.loads(base64.urlsafe_b64decode((cursor + pad).encode()))
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidCursorError from exc
    if not isinstance(decoded, list) or len(decoded) != expected:
        raise InvalidCursorError
    return decoded


def _cursor_values(row: Row, keyset: Sequence[InstrumentedAttribute]) -> list:
    return [getattr(next(v for v in row if isinstance(v, cast("type", attr.class_))), attr.key) for attr in keyset]


def _coerce(attr: InstrumentedAttribute, raw: object) -> object:
    python_type = attr.type.python_type
    if python_type is datetime:
        return datetime.fromisoformat(cast("str", raw))
    if python_type is int:
        return int(cast("str | int", raw))
    return raw


async def paginate[T](
    session: AsyncSession,
    stmt: Select,
    *,
    keyset: Sequence[InstrumentedAttribute],
    cursor: str | None,
    limit: int,
    into: Callable[[Row], T] | None = None,
) -> CursorPage[T]:
    if cursor is not None:
        decoded = decode_cursor(cursor, expected=len(keyset))
        bound = tuple(_coerce(attr, raw) for attr, raw in zip(keyset, decoded, strict=True))
        stmt = stmt.where(tuple_(*keyset) > bound)
    stmt = stmt.order_by(*keyset).limit(limit + 1)
    rows = (await session.execute(stmt)).all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    items = [into(row) if into is not None else row[0] for row in page_rows]
    next_cursor = encode_cursor(*_cursor_values(page_rows[-1], keyset)) if has_more else None
    return CursorPage(items=items, next_cursor=next_cursor)
