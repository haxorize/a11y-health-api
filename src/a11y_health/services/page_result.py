import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import InvalidAxePayloadError
from a11y_health.models.node_finding import NodeFinding
from a11y_health.models.page_result import PageResult
from a11y_health.models.rule_finding import FindingType, Impact, RuleFinding
from a11y_health.services.scan_run import assert_scan_run_pending, get_scan_run

_WCAG_VERSION_LEVEL = re.compile(r"^wcag2(1|2)?a{1,2}$")
_WCAG_CRITERION = re.compile(r"^wcag(\d)(\d)(\d+)$")
_CAT_TAG = re.compile(r"^cat\.(.+)$")


def _extract_classifications(tags: list[str]) -> list[dict[str, str]]:
    classifications: list[dict[str, str]] = []
    for tag in tags:
        if tag == "best-practice":
            classifications.append({"standard": "best-practice"})
            continue
        m = _WCAG_VERSION_LEVEL.match(tag)
        if m:
            version_suffix = m.group(1)
            if version_suffix == "2":
                version = "2.2"
            elif version_suffix == "1":
                version = "2.1"
            else:
                version = "2.0"
            level = "AA" if tag.endswith("aa") else "A"
            classifications.append({"standard": "wcag", "version": version, "level": level})
    return classifications


def _extract_wcag_criterion(tags: list[str]) -> str | None:
    for tag in tags:
        m = _WCAG_CRITERION.match(tag)
        if m:
            return f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
    return None


def _extract_category(tags: list[str]) -> str | None:
    for tag in tags:
        m = _CAT_TAG.match(tag)
        if m:
            return m.group(1)
    return None


_REQUIRED_RULE_FIELDS = ("id", "impact", "description", "help", "helpUrl")


def _parse_findings(
    page_result_id: int,
    rules: list[dict[str, Any]],
    finding_type: FindingType,
) -> tuple[list[RuleFinding], list[tuple[RuleFinding, NodeFinding]]]:
    rule_findings: list[RuleFinding] = []
    node_pairs: list[tuple[RuleFinding, NodeFinding]] = []

    for rule in rules:
        missing = [f for f in _REQUIRED_RULE_FIELDS if f not in rule]
        if missing:
            rule_id = rule.get("id", "<unknown>")
            raise InvalidAxePayloadError(f"Rule '{rule_id}' is missing required fields: {', '.join(missing)}")
        tags = rule.get("tags", [])
        rf = RuleFinding(
            page_result_id=page_result_id,
            rule_id=rule["id"],
            type=finding_type,
            impact=Impact(rule["impact"]),
            description=rule["description"],
            help=rule["help"],
            help_url=rule["helpUrl"],
            category=_extract_category(tags),
            wcag_criterion=_extract_wcag_criterion(tags),
            classifications=_extract_classifications(tags),
            tags=tags,
        )
        rule_findings.append(rf)

        for node in rule.get("nodes", []):
            checks = {
                "any": node.get("any", []),
                "all": node.get("all", []),
                "none": node.get("none", []),
            }
            nf = NodeFinding(
                html=node["html"],
                target=node["target"],
                impact=Impact(node["impact"]),
                failure_summary=node.get("failureSummary"),
                checks=checks,
            )
            node_pairs.append((rf, nf))

    return rule_findings, node_pairs


async def create_page_result(session: AsyncSession, scan_run_id: int, payload: dict[str, Any]) -> PageResult:
    scan_run = await get_scan_run(session, scan_run_id)
    assert_scan_run_pending(scan_run)

    if not isinstance(payload.get("findings"), dict):
        raise InvalidAxePayloadError("Payload must contain a 'findings' object")

    findings = payload["findings"]
    url = payload.get("testSubject", {}).get("fileName", "")

    if not url:
        raise InvalidAxePayloadError("Payload must contain a non-empty URL at 'testSubject.fileName'")

    validated_sections: list[tuple[FindingType, list[dict[str, Any]]]] = []
    for section, finding_type in [("violations", FindingType.VIOLATION), ("incomplete", FindingType.INCOMPLETE)]:
        value = findings.get(section, [])
        if not isinstance(value, list):
            raise InvalidAxePayloadError(f"'findings.{section}' must be a list")
        validated_sections.append((finding_type, value))

    page_result = PageResult(
        scan_run_id=scan_run_id,
        url=url,
        raw_json=payload,
        passes_count=len(findings.get("passes", [])),
        inapplicable_count=len(findings.get("inapplicable", [])),
    )
    session.add(page_result)
    await session.flush()

    all_rule_findings: list[RuleFinding] = []
    all_node_pairs: list[tuple[RuleFinding, NodeFinding]] = []

    for finding_type, rules in validated_sections:
        rule_findings, node_pairs = _parse_findings(page_result.id, rules, finding_type)
        all_rule_findings.extend(rule_findings)
        all_node_pairs.extend(node_pairs)

    if all_rule_findings:
        session.add_all(all_rule_findings)
        await session.flush()

    if all_node_pairs:
        for rf, nf in all_node_pairs:
            nf.rule_finding_id = rf.id
        session.add_all(nf for _, nf in all_node_pairs)
        await session.flush()

    await session.refresh(page_result)
    return page_result
