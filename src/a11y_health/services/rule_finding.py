from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import array
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer
from sqlalchemy.types import Text

from a11y_health.core import existence
from a11y_health.core.pagination import DEFAULT_PAGE_SIZE, CursorPage, paginate
from a11y_health.models.enums import Category, FindingType, Impact
from a11y_health.models.node_finding import NodeFinding
from a11y_health.models.page_result import PageResult
from a11y_health.models.rule_finding import RuleFinding
from a11y_health.models.scan_run import ScanRun
from a11y_health.schemas._tag_parsing import Classification, classification_to_tag
from a11y_health.schemas.rule_finding import NodeFindingDetail, RuleFindingDetail, RuleFindingRead


async def list_findings(
    session: AsyncSession,
    scan_run_id: int,
    *,
    finding_type: list[FindingType] | None = None,
    impact: list[Impact] | None = None,
    category: list[Category] | None = None,
    wcag_criterion: list[str] | None = None,
    classification: list[Classification] | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> CursorPage[RuleFindingRead]:
    await existence.get_by_pk(session, ScanRun, scan_run_id)

    # Correlated subquery, not outerjoin + GROUP BY: the count then runs only for
    # the limit+1 rows the page returns (an index probe each), instead of
    # aggregating every Node Finding in the scan run before LIMIT applies.
    node_finding_count = (
        select(func.count())
        .where(NodeFinding.rule_finding_id == RuleFinding.id)
        .correlate(RuleFinding)
        .scalar_subquery()
        .label("node_finding_count")
    )
    stmt = (
        select(RuleFinding, node_finding_count)
        .join(PageResult, RuleFinding.page_result_id == PageResult.id)
        .where(PageResult.scan_run_id == scan_run_id)
    )

    if finding_type:
        stmt = stmt.where(RuleFinding.type.in_(finding_type))
    if impact:
        stmt = stmt.where(RuleFinding.impact.in_(impact))
    if category:
        stmt = stmt.where(RuleFinding.category.in_(category))
    if wcag_criterion:
        stmt = stmt.where(RuleFinding.wcag_criteria.has_any(array(wcag_criterion, type_=Text)))
    if classification:
        targets = [classification_to_tag(c) for c in classification]
        stmt = stmt.where(or_(*(RuleFinding.classifications.contains([t]) for t in targets)))

    return await paginate(
        session,
        stmt,
        keyset=[RuleFinding.id],
        cursor=cursor,
        limit=limit,
        into=lambda r: RuleFindingRead.from_finding(r.RuleFinding, node_finding_count=r.node_finding_count),
    )


async def get_finding(
    session: AsyncSession,
    scan_run_id: int,
    finding_id: int,
) -> RuleFindingDetail:
    await existence.get_by_pk(session, ScanRun, scan_run_id)

    stmt = (
        select(RuleFinding)
        .join(PageResult, RuleFinding.page_result_id == PageResult.id)
        .where(PageResult.scan_run_id == scan_run_id, RuleFinding.id == finding_id)
    )
    finding = await existence.get_by_query(session, RuleFinding, stmt, finding_id)

    nodes_stmt = (
        select(NodeFinding)
        .where(NodeFinding.rule_finding_id == finding_id)
        .options(undefer(NodeFinding.checks))
        .order_by(NodeFinding.id)
    )
    nodes_result = await session.execute(nodes_stmt)

    return RuleFindingDetail.from_finding(
        finding,
        node_findings=[NodeFindingDetail.model_validate(nf) for nf in nodes_result.scalars()],
    )
