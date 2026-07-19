"""Parsing axe's open tag vocabulary into our domain enums.

Maps a rule's raw `tags` list onto a Category, its WCAG Criteria, and its
Classifications (WCAG version/level pairs or best-practice). `axe_payload.py`
owns the ingest-side parsing; the findings filter (service and endpoint) reads
the `ClassificationToken` vocabulary and `token_to_stored_classification` from
here so query and storage can never disagree, and the filter-options
enumeration reads `wcag_criterion_sort_key` so response ordering stays with
the code that mints the criterion format. Unknown WCAG-shaped tags are dropped
rather than rejected, since the axe tag set is open-ended.

See `DOMAIN.md` for Category, WCAG Criteria, and Classification.
"""

import re
from typing import Literal, get_args

from a11y_health.models.classification import Classification
from a11y_health.models.enums import Category

_WCAG_CRITERION = re.compile(r"^wcag(\d)(\d)(\d+)$")
_CAT_TAG = re.compile(r"^cat\.(.+)$")


ClassificationToken = Literal[
    "wcag2a",
    "wcag2aa",
    "wcag2aaa",
    "wcag21a",
    "wcag21aa",
    "wcag21aaa",
    "wcag22a",
    "wcag22aa",
    "wcag22aaa",
    "best-practice",
]


_TOKEN_TO_CLASSIFICATION: dict[str, Classification] = {
    "wcag2a": Classification(standard="wcag", version="2.0", level="A"),
    "wcag2aa": Classification(standard="wcag", version="2.0", level="AA"),
    "wcag2aaa": Classification(standard="wcag", version="2.0", level="AAA"),
    "wcag21a": Classification(standard="wcag", version="2.1", level="A"),
    "wcag21aa": Classification(standard="wcag", version="2.1", level="AA"),
    "wcag21aaa": Classification(standard="wcag", version="2.1", level="AAA"),
    "wcag22a": Classification(standard="wcag", version="2.2", level="A"),
    "wcag22aa": Classification(standard="wcag", version="2.2", level="AA"),
    "wcag22aaa": Classification(standard="wcag", version="2.2", level="AAA"),
    "best-practice": Classification(standard="best-practice"),
}

# The Literal feeds the OpenAPI enum; the map feeds storage and the filter. A missing
# map entry would 500 on a contractually valid token, so drift fails at import instead
# (an explicit raise, not an assert — asserts vanish under python -O).
if set(get_args(ClassificationToken)) != _TOKEN_TO_CLASSIFICATION.keys():
    raise RuntimeError("ClassificationToken and _TOKEN_TO_CLASSIFICATION have drifted")


def token_to_stored_classification(token: ClassificationToken) -> dict[str, str]:
    return _TOKEN_TO_CLASSIFICATION[token].stored()


def extract_classifications(tags: list[str]) -> list[Classification]:
    return [_TOKEN_TO_CLASSIFICATION[tag] for tag in tags if tag in _TOKEN_TO_CLASSIFICATION]


def extract_wcag_criteria(tags: list[str]) -> list[str]:
    results: list[str] = []
    for tag in tags:
        m = _WCAG_CRITERION.match(tag)
        if m:
            results.append(f"{m.group(1)}.{m.group(2)}.{m.group(3)}")
    return results


def wcag_criterion_sort_key(criterion: str) -> tuple[int, tuple[int, ...], str]:
    """Numeric segment order, so 1.4.13 sorts between 1.4.3 and 1.10.1.

    The column carries no format constraint (ADR 0014), so an out-of-shape
    value sorts last instead of failing the read that sorts it.
    """
    parts = criterion.split(".")
    if all(part.isdigit() for part in parts):
        return (0, tuple(int(part) for part in parts), "")
    return (1, (), criterion)


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
