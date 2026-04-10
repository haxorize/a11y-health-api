import re
from typing import Literal

_WCAG_VERSION_LEVEL = re.compile(r"^wcag2(1|2)?a{1,2}$")
_VERSION_MAP: dict[str | None, str] = {None: "2.0", "1": "2.1", "2": "2.2"}

Classification = Literal[
    "wcag2a",
    "wcag2aa",
    "wcag21a",
    "wcag21aa",
    "wcag22a",
    "wcag22aa",
    "best-practice",
]

VALID_CLASSIFICATIONS: frozenset[Classification] = frozenset(Classification.__args__)


def parse_wcag_tag(tag: str) -> dict[str, str] | None:
    """Parse a single axe WCAG tag into a classification dict, or None if unrecognized."""
    if tag == "best-practice":
        return {"standard": "best-practice"}
    m = _WCAG_VERSION_LEVEL.match(tag)
    if not m:
        return None
    version = _VERSION_MAP[m.group(1)]
    level = "AA" if tag.endswith("aa") else "A"
    return {"standard": "wcag", "version": version, "level": level}
