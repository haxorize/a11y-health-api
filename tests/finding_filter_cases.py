from dataclasses import dataclass, fields
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.classification import classifications_in
from a11y_health.models.enums import Category, FindingType, Impact
from a11y_health.schemas.rule_finding import FindingFilters
from tests.factories import make_rule_finding

_MATCHING_RULE_IDS = ("image-alt", "link-name")


@dataclass(frozen=True)
class FilterCase:
    matching: tuple[dict[str, Any], ...]
    # None when the filter selects every value, leaving nothing to exclude.
    other: dict[str, Any] | None
    filters: FindingFilters
    query: dict[str, list[str]]

    @property
    def dimensions(self) -> set[str]:
        return {dimension.name for dimension in fields(self.filters) if getattr(self.filters, dimension.name)}

    # Returns the rule ids of the findings the filter should keep. Strict, so a
    # case with more matching values than rule ids fails instead of seeding a
    # subset.
    async def seed(self, session: AsyncSession, page_result_id: int) -> set[str]:
        rule_ids = _MATCHING_RULE_IDS[: len(self.matching)]
        for rule_id, kwargs in zip(rule_ids, self.matching, strict=True):
            await make_rule_finding(session, page_result_id=page_result_id, rule_id=rule_id, **kwargs)
        if self.other is not None:
            await make_rule_finding(session, page_result_id=page_result_id, rule_id="meta-viewport", **self.other)
        return set(rule_ids)


# One case per findings filter dimension: factory kwargs for a finding per
# selected value and for one matching none, the service filter selecting those
# values, and the query string that decodes to it. The service suite reads the
# semantics off it and the API suite the decode, so a new dimension can't land
# in one and not the other. Finding Type has two values, so its any-of case
# selects both and has nothing to exclude.
FILTER_CASES = [
    pytest.param(
        FilterCase(
            matching=({"finding_type": FindingType.VIOLATION},),
            other={"finding_type": FindingType.INCOMPLETE},
            filters=FindingFilters(finding_type=[FindingType.VIOLATION]),
            query={"type": ["violation"]},
        ),
        id="finding_type",
    ),
    pytest.param(
        FilterCase(
            matching=({"finding_type": FindingType.VIOLATION}, {"finding_type": FindingType.INCOMPLETE}),
            other=None,
            filters=FindingFilters(finding_type=[FindingType.VIOLATION, FindingType.INCOMPLETE]),
            query={"type": ["violation", "incomplete"]},
        ),
        id="finding_type-both",
    ),
    pytest.param(
        FilterCase(
            matching=({"impact": Impact.CRITICAL}, {"impact": Impact.SERIOUS}),
            other={"impact": Impact.MINOR},
            filters=FindingFilters(impact=[Impact.CRITICAL, Impact.SERIOUS]),
            query={"impact": ["critical", "serious"]},
        ),
        id="impact",
    ),
    pytest.param(
        FilterCase(
            matching=({"category": Category.KEYBOARD}, {"category": Category.FORMS}),
            other={"category": Category.COLOR},
            filters=FindingFilters(category=[Category.KEYBOARD, Category.FORMS]),
            query={"category": ["keyboard", "forms"]},
        ),
        id="category",
    ),
    pytest.param(
        FilterCase(
            matching=({"wcag_criteria": ["2.4.4"]}, {"wcag_criteria": ["4.1.2"]}),
            other={"wcag_criteria": ["1.4.3"]},
            filters=FindingFilters(wcag_criterion=["2.4.4", "4.1.2"]),
            query={"wcag_criterion": ["2.4.4", "4.1.2"]},
        ),
        id="wcag_criterion",
    ),
    pytest.param(
        FilterCase(
            matching=(
                {"classifications": classifications_in(["best-practice"])},
                {"classifications": classifications_in(["wcag21aa"])},
            ),
            other={"classifications": classifications_in(["wcag2aa"])},
            filters=FindingFilters(classification=["best-practice", "wcag21aa"]),
            query={"classification": ["best-practice", "wcag21aa"]},
        ),
        id="classification",
    ),
]
