from typing import Annotated

from fastapi import APIRouter, Query

from a11y_health.api.deps import DbSession
from a11y_health.core.error_contract import ErrorCode, error_responses
from a11y_health.core.pagination import PageParams, TotalledPage
from a11y_health.models.classification import ClassificationToken
from a11y_health.models.enums import Category, FindingType, Impact
from a11y_health.schemas.rule_finding import FindingFilterOptionsRead, RuleFindingDetail, RuleFindingRead
from a11y_health.services import rule_finding as rule_finding_service

router = APIRouter(prefix="/scan-runs/{scan_run_id}/findings", tags=["findings"])


@router.get("", responses=error_responses(ErrorCode.NOT_FOUND, ErrorCode.INVALID_CURSOR))
async def list_findings(
    db: DbSession,
    scan_run_id: int,
    pagination: PageParams,
    type: Annotated[list[FindingType] | None, Query()] = None,
    impact: Annotated[list[Impact] | None, Query()] = None,
    category: Annotated[list[Category] | None, Query()] = None,
    wcag_criterion: Annotated[list[str] | None, Query()] = None,
    classification: Annotated[list[ClassificationToken] | None, Query()] = None,
) -> TotalledPage[RuleFindingRead]:
    page = await rule_finding_service.list_findings(
        db,
        scan_run_id,
        finding_type=type,
        impact=impact,
        category=category,
        wcag_criterion=wcag_criterion,
        classification=classification,
        cursor=pagination.cursor,
        limit=pagination.limit,
    )
    return TotalledPage.from_totalled_cursor_page(page)


# Registered before /{finding_id} so the static segment isn't parsed as a finding id.
@router.get("/filter-options", responses=error_responses(ErrorCode.NOT_FOUND))
async def list_finding_filter_options(db: DbSession, scan_run_id: int) -> FindingFilterOptionsRead:
    return await rule_finding_service.list_filter_options(db, scan_run_id)


@router.get("/{finding_id}", responses=error_responses(ErrorCode.NOT_FOUND))
async def get_finding(
    db: DbSession,
    scan_run_id: int,
    finding_id: int,
) -> RuleFindingDetail:
    return await rule_finding_service.get_finding(db, scan_run_id, finding_id)
