"""Parsing axe's open tag vocabulary into our domain enums.

Maps a rule's raw `tags` list onto a Category, its WCAG Criteria, and its
Classifications (WCAG version/level pairs or best-practice). Private to the
schemas layer (`axe_payload.py` is the only caller); unknown WCAG-shaped tags are
dropped rather than rejected, since the axe tag set is open-ended.

See `DOMAIN.md` for Category, WCAG Criteria, and Classification.
"""

import re
from typing import Literal

from a11y_health.models.enums import Category

_WCAG_CRITERION = re.compile(r"^wcag(\d)(\d)(\d+)$")
_CAT_TAG = re.compile(r"^cat\.(.+)$")

Classification = Literal[
    "wcag2a",
    "wcag2aa",
    "wcag21a",
    "wcag21aa",
    "wcag22a",
    "wcag22aa",
    "best-practice",
]


_CLASSIFICATION_TO_TAG: dict[str, dict[str, str]] = {
    "wcag2a": {"standard": "wcag", "version": "2.0", "level": "A"},
    "wcag2aa": {"standard": "wcag", "version": "2.0", "level": "AA"},
    "wcag21a": {"standard": "wcag", "version": "2.1", "level": "A"},
    "wcag21aa": {"standard": "wcag", "version": "2.1", "level": "AA"},
    "wcag22a": {"standard": "wcag", "version": "2.2", "level": "A"},
    "wcag22aa": {"standard": "wcag", "version": "2.2", "level": "AA"},
    "best-practice": {"standard": "best-practice"},
}


def classification_to_tag(c: Classification) -> dict[str, str]:
    return _CLASSIFICATION_TO_TAG[c]


def extract_classifications(tags: list[str]) -> list[dict[str, str]]:
    return [_CLASSIFICATION_TO_TAG[tag] for tag in tags if tag in _CLASSIFICATION_TO_TAG]


def extract_wcag_criteria(tags: list[str]) -> list[str]:
    results: list[str] = []
    for tag in tags:
        m = _WCAG_CRITERION.match(tag)
        if m:
            results.append(f"{m.group(1)}.{m.group(2)}.{m.group(3)}")
    return results


_CATEGORY_LOOKUP = {c.value: c for c in Category}


def extract_category(tags: list[str]) -> Category:
    for tag in tags:
        m = _CAT_TAG.match(tag)
        if m:
            value = m.group(1)
            cat = _CATEGORY_LOOKUP.get(value)
            if cat is None:
                raise ValueError(f"Unknown category: {value}")
            return cat
    raise ValueError("No category tag found")
