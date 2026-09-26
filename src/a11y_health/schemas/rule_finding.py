from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from a11y_health.models.classification import Classification, ClassificationToken
from a11y_health.models.enums import Category, FindingType, Impact

if TYPE_CHECKING:
    from a11y_health.models.rule_finding import RuleFinding


# The findings filter dimensions, declared once: the endpoint takes it as a
# dependency, which flattens each field into a query parameter, and the service
# matches on each field it finds set. The published parameter for finding_type
# is `type`.
@dataclass(frozen=True)
class FindingFilters:
    finding_type: Annotated[list[FindingType] | None, Query(alias="type")] = None
    impact: Annotated[list[Impact] | None, Query()] = None
    category: Annotated[list[Category] | None, Query()] = None
    wcag_criterion: Annotated[list[str] | None, Query()] = None
    classification: Annotated[list[ClassificationToken] | None, Query()] = None


# Depends(), not Query(), for the reason `PageParams` gives.
FindingFilterParams = Annotated[FindingFilters, Depends()]


# The token is the findings filter's query vocabulary; the Classification is the
# structure it names, so clients derive labels from the contract instead of
# keeping their own token decode table (#125).
class ClassificationFilterOption(BaseModel):
    token: ClassificationToken
    classification: Classification


class FindingFilterOptionsRead(BaseModel):
    wcag_criteria: list[str] = Field(
        description=(
            "Distinct across the run, in numeric segment order (1.4.3 before 1.4.13 "
            "before 1.10.1). A value whose segments are not all digits sorts last, "
            "by string."
        )
    )
    classifications: list[ClassificationFilterOption] = Field(
        description="Distinct across the run, in vocabulary order (the order of the Classification Token literal)."
    )


class _RuleFindingBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    page_result_id: int
    rule_id: str
    type: FindingType
    impact: Impact
    description: str
    help: str
    help_url: str
    category: Category
    wcag_criteria: list[str]
    classifications: list[Classification]
    tags: list[str]


def _base_fields(finding: RuleFinding) -> dict[str, Any]:
    return {name: getattr(finding, name) for name in _RuleFindingBase.model_fields}


class RuleFindingRead(_RuleFindingBase):
    node_finding_count: int

    @classmethod
    def from_finding(cls, finding: RuleFinding, *, node_finding_count: int) -> RuleFindingRead:
        return cls(**_base_fields(finding), node_finding_count=node_finding_count)


class NodeFindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    html: str
    target: list[str]
    impact: Impact
    failure_summary: str | None


class NodeFindingDetail(NodeFindingRead):
    checks: dict[str, Any]


# Deliberately no node_finding_count here — the detail embeds the Node Findings
# themselves.
class RuleFindingDetail(_RuleFindingBase):
    node_findings: list[NodeFindingDetail] = Field(default_factory=list)

    @classmethod
    def from_finding(cls, finding: RuleFinding, *, node_findings: list[NodeFindingDetail]) -> RuleFindingDetail:
        return cls(**_base_fields(finding), node_findings=node_findings)
