"""Page-result ingest: the one service that performs the axe boundary crossing,
taking the raw document rather than a validated schema. See
`docs/architecture.md` ("The layers", under **Services**) for why the crossing
sits here.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core import existence
from a11y_health.core.exceptions import ScanRunCompletedError
from a11y_health.models.enums import FindingType, ScanRunStatus
from a11y_health.models.node_finding import NodeFinding
from a11y_health.models.page_result import PageResult
from a11y_health.models.rule_finding import RuleFinding
from a11y_health.models.scan_run import ScanRun
from a11y_health.schemas.axe_payload import AxeRule, parse_axe_payload


async def _persist_findings(
    session: AsyncSession,
    page_result_id: int,
    rules: list[AxeRule],
    finding_type: FindingType,
) -> None:
    rule_findings: list[RuleFinding] = []
    node_findings: list[tuple[RuleFinding, NodeFinding]] = []

    for rule in rules:
        rf = RuleFinding(
            page_result_id=page_result_id,
            rule_id=rule.id,
            type=finding_type,
            impact=rule.impact,
            description=rule.description,
            help=rule.help,
            help_url=rule.help_url,
            category=rule.category,
            wcag_criteria=rule.wcag_criteria,
            classifications=rule.classifications,
            tags=rule.tags,
        )
        rule_findings.append(rf)

        for node in rule.nodes:
            nf = NodeFinding(
                html=node.html,
                target=node.target,
                impact=node.impact,
                failure_summary=node.failure_summary,
                checks={"any": node.any, "all": node.all, "none": node.none},
            )
            node_findings.append((rf, nf))

    if rule_findings:
        session.add_all(rule_findings)
        await session.flush()

    if node_findings:
        for rf, nf in node_findings:
            nf.rule_finding_id = rf.id
        session.add_all(nf for _, nf in node_findings)
        await session.flush()


def _assert_scan_run_pending(scan_run: ScanRun) -> None:
    # Private to its one consumer. A second consumer promotes this to the
    # scan-run service rather than copying it — the copy is how two checks
    # drift.
    if scan_run.status == ScanRunStatus.COMPLETED:
        raise ScanRunCompletedError(scan_run.id)


async def create_page_result(session: AsyncSession, scan_run_id: int, raw_document: dict[str, Any]) -> PageResult:
    payload = parse_axe_payload(raw_document)
    scan_run = await existence.get_by_pk(session, ScanRun, scan_run_id)
    _assert_scan_run_pending(scan_run)

    page_result = PageResult(
        scan_run_id=scan_run_id,
        url=payload.test_subject.file_name,
        raw_json=raw_document,
        passes_count=len(payload.findings.passes),
        inapplicable_count=len(payload.findings.inapplicable),
    )
    session.add(page_result)
    await session.flush()

    await _persist_findings(session, page_result.id, payload.findings.violations, FindingType.VIOLATION)
    await _persist_findings(session, page_result.id, payload.findings.incomplete, FindingType.INCOMPLETE)

    await session.refresh(page_result)
    return page_result
