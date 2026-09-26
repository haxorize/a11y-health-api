from typing import Any

from sqlalchemy import Select, SQLColumnExpression, Subquery, func, select
from sqlalchemy.dialects.postgresql import JSONB, array
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer
from sqlalchemy.types import Text

from a11y_health.core import existence
from a11y_health.core.pagination import DEFAULT_PAGE_SIZE, TotalledCursorPage, paginate
from a11y_health.models.classification import ClassificationToken, classification_options
from a11y_health.models.enums import Category, FindingType, Impact
from a11y_health.models.node_finding import NodeFinding
from a11y_health.models.page_result import PageResult
from a11y_health.models.rule_finding import RuleFinding
from a11y_health.models.scan_run import ScanRun
from a11y_health.schemas.rule_finding import (
    ClassificationFilterOption,
    FindingFilterOptionsRead,
    NodeFindingDetail,
    RuleFindingDetail,
    RuleFindingRead,
)


def _scoped_to_run[SelectT: Select[Any]](stmt: SelectT, scan_run_id: int) -> SelectT:
    return stmt.join(PageResult, RuleFinding.page_result_id == PageResult.id).where(
        PageResult.scan_run_id == scan_run_id
    )


async def list_findings(
    session: AsyncSession,
    scan_run_id: int,
    *,
    finding_type: list[FindingType] | None = None,
    impact: list[Impact] | None = None,
    category: list[Category] | None = None,
    wcag_criterion: list[str] | None = None,
    classification: list[ClassificationToken] | None = None,
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> TotalledCursorPage[RuleFindingRead]:
    await existence.get_by_pk(session, ScanRun, scan_run_id)

    # Correlated subquery, not outerjoin + GROUP BY: the count then runs only
    # for the limit+1 rows the page returns (an index probe each), instead of
    # aggregating every Node Finding in the scan run before LIMIT applies.
    node_finding_count = (
        select(func.count())
        .where(NodeFinding.rule_finding_id == RuleFinding.id)
        .correlate(RuleFinding)
        .scalar_subquery()
        .label("node_finding_count")
    )
    stmt = _scoped_to_run(select(RuleFinding, node_finding_count), scan_run_id)

    if finding_type:
        stmt = stmt.where(RuleFinding.type.in_(finding_type))
    if impact:
        stmt = stmt.where(RuleFinding.impact.in_(impact))
    if category:
        stmt = stmt.where(RuleFinding.category.in_(category))
    if wcag_criterion:
        stmt = stmt.where(RuleFinding.wcag_criteria.has_any(array(wcag_criterion, type_=Text)))
    if classification:
        stmt = stmt.where(RuleFinding.classified_as_any(classification))

    return await paginate(
        session,
        stmt,
        keyset=[RuleFinding.id],
        cursor=cursor,
        limit=limit,
        into=lambda r: RuleFindingRead.from_finding(r.RuleFinding, node_finding_count=r.node_finding_count),
        with_total=True,
    )


def wcag_criterion_sort_key(criterion: str) -> tuple[int, tuple[int, ...], str]:
    """Numeric segment order, so 1.4.13 sorts between 1.4.3 and 1.10.1.

    The column carries no format constraint (ADR 0014), so an out-of-shape
    value sorts last instead of failing the read that sorts it.
    """
    parts = criterion.split(".")
    if all(part.isdigit() for part in parts):
        return (0, tuple(int(part) for part in parts), "")
    return (1, (), criterion)


# The jsonb_typeof guard shares a SELECT with a select-list expansion, which
# runs after WHERE, so a non-array value is skipped rather than raising.
def _elements_in_run(
    column: SQLColumnExpression[Any], expansion: SQLColumnExpression[Any], scan_run_id: int
) -> Subquery:
    return (
        _scoped_to_run(select(expansion.label("element")), scan_run_id)
        .where(func.jsonb_typeof(column) == "array")
        .subquery()
    )


# Filter Options (DOMAIN.md): the distinct values present across one Scan Run's
# Rule Findings, per filter dimension.
async def list_filter_options(session: AsyncSession, scan_run_id: int) -> FindingFilterOptionsRead:
    await existence.get_by_pk(session, ScanRun, scan_run_id)

    # One row back, not one per Rule Finding: Postgres expands and dedupes each
    # array, and the aggregate reads through the column's own type, so each
    # distinct Classification entry is validated once.
    criteria = _elements_in_run(
        RuleFinding.wcag_criteria, func.jsonb_array_elements_text(RuleFinding.wcag_criteria, type_=Text), scan_run_id
    )
    entries = _elements_in_run(
        RuleFinding.classifications, func.jsonb_array_elements(RuleFinding.classifications, type_=JSONB), scan_run_id
    )
    stmt = select(
        select(func.array_agg(criteria.c.element.distinct())).scalar_subquery(),
        select(func.jsonb_agg(entries.c.element.distinct(), type_=RuleFinding.classifications.type)).scalar_subquery(),
    )
    distinct_criteria, distinct_entries = (await session.execute(stmt)).one()
    options = classification_options(distinct_entries or [])
    return FindingFilterOptionsRead(
        wcag_criteria=sorted(distinct_criteria or [], key=wcag_criterion_sort_key),
        classifications=[
            ClassificationFilterOption(token=token, classification=classification) for token, classification in options
        ],
    )


async def get_finding(
    session: AsyncSession,
    scan_run_id: int,
    finding_id: int,
) -> RuleFindingDetail:
    await existence.get_by_pk(session, ScanRun, scan_run_id)

    stmt = _scoped_to_run(select(RuleFinding), scan_run_id).where(RuleFinding.id == finding_id)
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
