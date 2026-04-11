from fastapi import APIRouter, Query

from a11y_health.api.deps import DbSession
from a11y_health.models.enums import Impact
from a11y_health.schemas.rule_finding import NodeFindingRead, RuleFindingDetail, RuleFindingRead
from a11y_health.services import rule_finding as rule_finding_service
from a11y_health.services._tag_parsing import Classification

router = APIRouter(prefix="/scan-runs/{scan_run_id}/findings", tags=["findings"])


@router.get("")
async def list_findings(
    db: DbSession,
    scan_run_id: int,
    impact: Impact | None = None,
    category: str | None = None,
    wcag_criterion: str | None = None,
    classification: Classification | None = None,
    offset: int = 0,
    limit: int = Query(default=20, le=100),
) -> list[RuleFindingRead]:
    findings = await rule_finding_service.list_findings(
        db,
        scan_run_id,
        impact=impact,
        category=category,
        wcag_criterion=wcag_criterion,
        classification=classification,
        offset=offset,
        limit=limit,
    )
    return [RuleFindingRead.model_validate(f) for f in findings]


@router.get("/{finding_id}")
async def get_finding(
    db: DbSession,
    scan_run_id: int,
    finding_id: int,
) -> RuleFindingDetail:
    finding, node_findings = await rule_finding_service.get_finding(db, scan_run_id, finding_id)
    detail = RuleFindingDetail.model_validate(finding)
    detail.node_findings = [NodeFindingRead.model_validate(nf) for nf in node_findings]
    return detail
