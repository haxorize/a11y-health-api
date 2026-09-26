from dataclasses import dataclass
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.classification import token_to_stored_classification
from a11y_health.models.enums import Category, FindingType, Impact
from tests.factories import make_rule_finding

_MATCHING_RULE_IDS = ("image-alt", "link-name")


@dataclass(frozen=True)
class FilterCase:
    matching: tuple[dict[str, Any], ...]
    other: dict[str, Any]
    filters: dict[str, Any]
    query: dict[str, list[str]]

    # Returns the rule ids of the findings the filter should keep.
    async def seed(self, session: AsyncSession, page_result_id: int) -> set[str]:
        for rule_id, kwargs in zip(_MATCHING_RULE_IDS, self.matching, strict=False):
            await make_rule_finding(session, page_result_id=page_result_id, rule_id=rule_id, **kwargs)
        await make_rule_finding(session, page_result_id=page_result_id, rule_id="meta-viewport", **self.other)
        return set(_MATCHING_RULE_IDS[: len(self.matching)])


# One case per findings filter dimension: factory kwargs for a finding per
# selected value and for one matching none, the service filter selecting those
# values, and the query string that decodes to it. The service suite reads the
# semantics off it and the API suite the decode, so a new dimension can't land
# in one and not the other. Finding Type has two values, so selecting a second
# leaves nothing to exclude.
FILTER_CASES = [
    pytest.param(
        FilterCase(
            matching=({"finding_type": FindingType.VIOLATION},),
            other={"finding_type": FindingType.INCOMPLETE},
            filters={"finding_type": [FindingType.VIOLATION]},
            query={"type": ["violation"]},
        ),
        id="finding_type",
    ),
    pytest.param(
        FilterCase(
            matching=({"impact": Impact.CRITICAL}, {"impact": Impact.SERIOUS}),
            other={"impact": Impact.MINOR},
            filters={"impact": [Impact.CRITICAL, Impact.SERIOUS]},
            query={"impact": ["critical", "serious"]},
        ),
        id="impact",
    ),
    pytest.param(
        FilterCase(
            matching=({"category": Category.KEYBOARD}, {"category": Category.FORMS}),
            other={"category": Category.COLOR},
            filters={"category": [Category.KEYBOARD, Category.FORMS]},
            query={"category": ["keyboard", "forms"]},
        ),
        id="category",
    ),
    pytest.param(
        FilterCase(
            matching=({"wcag_criteria": ["2.4.4"]}, {"wcag_criteria": ["4.1.2"]}),
            other={"wcag_criteria": ["1.4.3"]},
            filters={"wcag_criterion": ["2.4.4", "4.1.2"]},
            query={"wcag_criterion": ["2.4.4", "4.1.2"]},
        ),
        id="wcag_criterion",
    ),
    pytest.param(
        FilterCase(
            matching=(
                {"classifications": [token_to_stored_classification("best-practice")]},
                {"classifications": [token_to_stored_classification("wcag21aa")]},
            ),
            other={"classifications": [token_to_stored_classification("wcag2aa")]},
            filters={"classification": ["best-practice", "wcag21aa"]},
            query={"classification": ["best-practice", "wcag21aa"]},
        ),
        id="classification",
    ),
]
