"""Parsing axe's tag syntax into our domain values, for ingest.

Maps a rule's raw `tags` list onto a Category and its WCAG Criteria — the two
values that have to be read *out of* the tag's shape. Genuinely private to this
package: `axe_payload.py` is the only importer. Classifications are not here,
because naming one takes no tag syntax at all, only the closed vocabulary in
`models/classification.py`, which screens the same list itself. Unknown
WCAG-shaped tags are dropped rather than rejected, since the axe tag set is
open-ended. The category tag is the deliberate exception: `extract_category`
rejects a rule without a known one.

See `DOMAIN.md` for Category and WCAG Criteria.
"""

import re

from a11y_health.models.enums import Category

_WCAG_CRITERION = re.compile(r"^wcag(\d)(\d)(\d+)$")
_CAT_TAG = re.compile(r"^cat\.(.+)$")


def extract_wcag_criteria(tags: list[str]) -> list[str]:
    results: list[str] = []
    for tag in tags:
        m = _WCAG_CRITERION.match(tag)
        if m:
            results.append(f"{m.group(1)}.{m.group(2)}.{m.group(3)}")
    return results


_CATEGORY_LOOKUP = {c.value: c for c in Category}


def extract_category(tags: list[str]) -> Category:
    """Raises `ValueError` when no `cat.*` category tag is present, or when its
    value is not a known Category. `AxeRule`'s validator lets either through,
    and `parse_axe_payload` turns it into a rejected Axe Payload, the 400
    `invalid_axe_payload`."""
    for tag in tags:
        m = _CAT_TAG.match(tag)
        if m:
            value = m.group(1)
            cat = _CATEGORY_LOOKUP.get(value)
            if cat is None:
                raise ValueError(f"Unknown category: {value}")
            return cat
    raise ValueError("No category tag found")
