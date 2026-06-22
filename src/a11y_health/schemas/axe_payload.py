"""The validated boundary for incoming axe DevTools JSON.

All validation of an uploaded payload — structural and semantic (impact values,
classification shape, WCAG criteria parsing) — happens here at the API edge, so
services downstream receive a trusted `AxePayload` and never re-check raw dicts.
Tag-vocabulary parsing is delegated to `_tag_parsing.py`.

See `docs/architecture.md` ("The layers") and
`docs/adr/0009-axe-payload-pydantic-boundary.md`.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from a11y_health.models.enums import Category, Impact
from a11y_health.schemas._tag_parsing import extract_category, extract_classifications, extract_wcag_criteria


class AxeNode(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    html: str
    target: list[str]
    impact: Impact
    failure_summary: str | None = Field(default=None, alias="failureSummary")
    any: list[dict[str, Any]] = Field(default_factory=list)
    all: list[dict[str, Any]] = Field(default_factory=list)
    none: list[dict[str, Any]] = Field(default_factory=list)


class AxeRule(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    impact: Impact
    description: str
    help: str
    help_url: str = Field(alias="helpUrl")
    tags: list[str]
    nodes: list[AxeNode]
    category: Category
    wcag_criteria: list[str]
    classifications: list[dict[str, str]]

    @model_validator(mode="before")
    @classmethod
    def classify_tags(cls, data: Any) -> Any:
        # Unknown WCAG-shaped tags are silently dropped; the axe tag vocabulary is open.
        if isinstance(data, dict):
            tags = data.get("tags", [])
            return {
                **data,
                "category": extract_category(tags),
                "wcag_criteria": extract_wcag_criteria(tags),
                "classifications": extract_classifications(tags),
            }
        return data


class AxeFindings(BaseModel):
    violations: list[AxeRule]
    incomplete: list[AxeRule]
    passes: list[Any] = Field(default_factory=list)
    inapplicable: list[Any] = Field(default_factory=list)


class AxeTestSubject(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    file_name: str = Field(min_length=1, alias="fileName")


class AxePayload(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    test_subject: AxeTestSubject = Field(alias="testSubject")
    findings: AxeFindings
