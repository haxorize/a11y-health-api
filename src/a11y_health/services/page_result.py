from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.enums import FindingType, Impact
from a11y_health.models.node_finding import NodeFinding
from a11y_health.models.page_result import PageResult
from a11y_health.models.rule_finding import RuleFinding
from a11y_health.schemas.axe_payload import AxePayload, AxeRule
from a11y_health.services._tag_parsing import extract_category, extract_classifications, extract_wcag_criterion
from a11y_health.services.scan_run import assert_scan_run_pending, get_scan_run

_AXE_SECTION_FINDING_TYPE: list[tuple[FindingType, str]] = [
    (FindingType.VIOLATION, "violations"),
    (FindingType.INCOMPLETE, "incomplete"),
]


async def _persist_findings(
    session: AsyncSession,
    page_result_id: int,
    rules: list[AxeRule],
    finding_type: FindingType,
    raw_rules: list[dict[str, Any]],
) -> None:
    rule_findings: list[RuleFinding] = []
    node_findings: list[tuple[RuleFinding, NodeFinding]] = []

    for rule, raw_rule in zip(rules, raw_rules, strict=True):
        rf = RuleFinding(
            page_result_id=page_result_id,
            rule_id=rule.id,
            type=finding_type,
            impact=Impact(rule.impact),
            description=rule.description,
            help=rule.help,
            help_url=rule.help_url,
            category=extract_category(rule.tags),
            wcag_criterion=extract_wcag_criterion(rule.tags),
            classifications=extract_classifications(rule.tags),
            tags=rule.tags,
        )
        rule_findings.append(rf)

        for node, raw_node in zip(rule.nodes, raw_rule.get("nodes", []), strict=True):
            checks = {
                "any": raw_node.get("any", []),
                "all": raw_node.get("all", []),
                "none": raw_node.get("none", []),
            }
            nf = NodeFinding(
                html=node.html,
                target=node.target,
                impact=Impact(node.impact),
                failure_summary=node.failure_summary,
                checks=checks,
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


async def create_page_result(
    session: AsyncSession, scan_run_id: int, payload: AxePayload, raw_payload: dict[str, Any]
) -> PageResult:
    scan_run = await get_scan_run(session, scan_run_id)
    assert_scan_run_pending(scan_run)

    raw_findings = raw_payload.get("findings", {})

    page_result = PageResult(
        scan_run_id=scan_run_id,
        url=payload.test_subject.file_name,
        raw_json=raw_payload,
        passes_count=len(raw_findings.get("passes", [])),
        inapplicable_count=len(raw_findings.get("inapplicable", [])),
    )
    session.add(page_result)
    await session.flush()

    for finding_type, section in _AXE_SECTION_FINDING_TYPE:
        typed_rules = getattr(payload.findings, section)
        raw_rules = raw_findings.get(section, [])
        await _persist_findings(session, page_result.id, typed_rules, finding_type, raw_rules)

    await session.refresh(page_result)
    return page_result
