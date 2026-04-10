import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.page_result import PageResult
from a11y_health.models.rule_finding import Impact, RuleFinding
from a11y_health.services.scan_run import get_scan_run

_CLASSIFICATION_PATTERN = re.compile(r"^wcag2([12])?a{1,2}$")

_VALID_CLASSIFICATIONS = {
    "wcag2a",
    "wcag2aa",
    "wcag21a",
    "wcag21aa",
    "wcag22a",
    "wcag22aa",
    "best-practice",
}

_VERSION_MAP = {None: "2.0", "1": "2.1", "2": "2.2"}


def _parse_classification(value: str) -> dict[str, str]:
    if value not in _VALID_CLASSIFICATIONS:
        raise ValueError(f"Invalid classification: {value}")
    if value == "best-practice":
        return {"standard": "best-practice"}
    m = _CLASSIFICATION_PATTERN.match(value)
    assert m  # guaranteed by _VALID_CLASSIFICATIONS check
    version = _VERSION_MAP[m.group(1)]
    level = "AA" if value.endswith("aa") else "A"
    return {"standard": "wcag", "version": version, "level": level}


async def list_findings(
    session: AsyncSession,
    scan_run_id: int,
    *,
    impact: Impact | None = None,
    category: str | None = None,
    wcag_criterion: str | None = None,
    classification: str | None = None,
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
