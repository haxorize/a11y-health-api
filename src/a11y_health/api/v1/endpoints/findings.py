from fastapi import APIRouter, Query

from a11y_health.api.deps import DbSession
from a11y_health.models.enums import Category, FindingType, Impact
from a11y_health.schemas.rule_finding import NodeFindingRead, RuleFindingDetail, RuleFindingRead
from a11y_health.services import rule_finding as rule_finding_service
from a11y_health.services._tag_parsing import Classification

router = APIRouter(prefix="/scan-runs/{scan_run_id}/findings", tags=["findings"])


@router.get("")
async def list_findings(
    db: DbSession,
    scan_run_id: int,
    type: list[FindingType] | None = Query(default=None),  # noqa: B008
    impact: list[Impact] | None = Query(default=None),  # noqa: B008
    category: list[Category] | None = Query(default=None),  # noqa: B008
    wcag_criterion: list[str] | None = Query(default=None),  # noqa: B008
    classification: list[Classification] | None = Query(default=None),  # noqa: B008
    offset: int = 0,
    limit: int = Query(default=20, le=100),  # noqa: B008
) -> list[RuleFindingRead]:
    findings = await rule_finding_service.list_findings(
        db,
        scan_run_id,
        finding_type=type,
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
    result = await rule_finding_service.get_finding(db, scan_run_id, finding_id)
    finding_data = RuleFindingRead.model_validate(result.finding)
    return RuleFindingDetail(
        **finding_data.model_dump(),
        node_findings=[NodeFindingRead.model_validate(nf) for nf in result.node_findings],
    )
