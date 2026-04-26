import base64
import json
from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel


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
