from typing import Annotated

from fastapi import APIRouter, Query

from a11y_health.api.deps import DbSession
from a11y_health.core.pagination import Page
from a11y_health.models.enums import Category, FindingType, Impact
from a11y_health.schemas._tag_parsing import Classification
from a11y_health.schemas.rule_finding import NodeFindingDetail, RuleFindingDetail, RuleFindingRead
from a11y_health.services import rule_finding as rule_finding_service

router = APIRouter(prefix="/scan-runs/{scan_run_id}/findings", tags=["findings"])


@router.get("")
async def list_findings(
    db: DbSession,
    scan_run_id: int,
    type: Annotated[list[FindingType] | None, Query()] = None,
    impact: Annotated[list[Impact] | None, Query()] = None,
    category: Annotated[list[Category] | None, Query()] = None,
    wcag_criterion: Annotated[list[str] | None, Query()] = None,
    classification: Annotated[list[Classification] | None, Query()] = None,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> Page[RuleFindingRead]:
    page = await rule_finding_service.list_findings(
        db,
        scan_run_id,
        finding_type=type,
        impact=impact,
        category=category,
        wcag_criterion=wcag_criterion,
        classification=classification,
        cursor=cursor,
        limit=limit,
    )
    return Page(items=[RuleFindingRead.model_validate(f) for f in page.items], next_cursor=page.next_cursor)


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
        node_findings=[NodeFindingDetail.model_validate(nf) for nf in result.node_findings],
    )
