from typing import Any

from pydantic import BaseModel, ConfigDict

from a11y_health.models.rule_finding import FindingType, Impact

__all__ = ["NodeFindingRead", "RuleFindingDetail", "RuleFindingRead"]


class RuleFindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    page_result_id: int
    rule_id: str
    type: FindingType
    impact: Impact
    description: str
    help: str
    help_url: str
    category: str | None
    wcag_criterion: str | None
    classifications: list[dict[str, str]]
    tags: list[str]


class NodeFindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    html: str
    target: list[str]
    impact: Impact
    failure_summary: str | None
    checks: dict[str, Any]


class RuleFindingDetail(RuleFindingRead):
    node_findings: list[NodeFindingRead] = []
