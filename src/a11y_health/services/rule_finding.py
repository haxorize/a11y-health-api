from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from a11y_health.core.exceptions import InvalidAxePayloadError, NotFoundError
from a11y_health.models.enums import Impact
from a11y_health.models.node_finding import NodeFinding
from a11y_health.models.page_result import PageResult
from a11y_health.models.rule_finding import RuleFinding
from a11y_health.services._tag_parsing import Classification, parse_wcag_tag
from a11y_health.services.scan_run import get_scan_run

_RESOURCE = "Finding"


def _parse_classification(value: str) -> dict[str, str]:
    parsed = parse_wcag_tag(value)
    if parsed is None:
        raise InvalidAxePayloadError(f"Invalid classification: {value}")
    return parsed


async def list_findings(
    session: AsyncSession,
    scan_run_id: int,
    *,
    impact: Impact | None = None,
    category: str | None = None,
    wcag_criterion: str | None = None,
    classification: Classification | None = None,
    offset: int = 0,
    limit: int = 20,
) -> list[RuleFinding]:
    await get_scan_run(session, scan_run_id)

    stmt = (
        select(RuleFinding)
        .join(PageResult, RuleFinding.page_result_id == PageResult.id)
        .where(PageResult.scan_run_id == scan_run_id)
    )

    if impact is not None:
        stmt = stmt.where(RuleFinding.impact == impact)
    if category is not None:
        stmt = stmt.where(RuleFinding.category == category)
    if wcag_criterion is not None:
        stmt = stmt.where(RuleFinding.wcag_criterion == wcag_criterion)
    if classification is not None:
        target = _parse_classification(classification)
        stmt = stmt.where(RuleFinding.classifications.contains([target]))

    stmt = stmt.order_by(RuleFinding.id).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_finding(
    session: AsyncSession,
    scan_run_id: int,
    finding_id: int,
) -> tuple[RuleFinding, list[NodeFinding]]:
    await get_scan_run(session, scan_run_id)

    stmt = (
        select(RuleFinding)
        .join(PageResult, RuleFinding.page_result_id == PageResult.id)
        .where(PageResult.scan_run_id == scan_run_id, RuleFinding.id == finding_id)
    )
    result = await session.execute(stmt)
    finding = result.scalar_one_or_none()
    if finding is None:
        raise NotFoundError(_RESOURCE, finding_id)

    nodes_stmt = (
        select(NodeFinding)
        .where(NodeFinding.rule_finding_id == finding_id)
        .options(undefer(NodeFinding.checks))
        .order_by(NodeFinding.id)
    )
    nodes_result = await session.execute(nodes_stmt)
    node_findings = list(nodes_result.scalars().all())

    return finding, node_findings
