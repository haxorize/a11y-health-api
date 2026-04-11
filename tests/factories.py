from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.app import App
from a11y_health.models.enums import Brand, FindingType, Impact, ScanRunStatus
from a11y_health.models.node_finding import NodeFinding
from a11y_health.models.org_unit import OrgUnit
from a11y_health.models.page_result import PageResult
from a11y_health.models.rule_finding import RuleFinding
from a11y_health.models.scan_run import ScanRun
from a11y_health.models.score_snapshot import ScoreSnapshot
from a11y_health.schemas.axe_payload import AxePayload
from a11y_health.services.score import build_snapshot


async def make_org_unit(db: AsyncSession, *, name: str = "Test Org", parent_id: int | None = None) -> OrgUnit:
    org_unit = OrgUnit(name=name, parent_id=parent_id)
    db.add(org_unit)
    await db.flush()
    return org_unit


async def make_app(
    db: AsyncSession,
    *,
    name: str = "Test App",
    slug: str = "test-app",
    brand: Brand = Brand.HUMANA,
    org_unit_id: int,
) -> App:
    app = App(name=name, slug=slug, brand=brand, org_unit_id=org_unit_id)
    db.add(app)
    await db.flush()
    return app


async def make_scan_run(
    db: AsyncSession,
    *,
    app_id: int,
    status: ScanRunStatus = ScanRunStatus.PENDING,
    scanned_at: datetime | None = None,
) -> ScanRun:
    scan_run = ScanRun(
        app_id=app_id,
        status=status,
        scanned_at=scanned_at or datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
    )
    db.add(scan_run)
    await db.flush()
    return scan_run


async def make_app_with_org_unit(
    db: AsyncSession,
    *,
    org_name: str = "Test Org",
    app_name: str = "Test App",
    slug: str = "test-app",
    brand: Brand = Brand.HUMANA,
) -> App:
    org_unit = await make_org_unit(db, name=org_name)
    return await make_app(db, name=app_name, slug=slug, brand=brand, org_unit_id=org_unit.id)


async def make_scan_run_with_parents(
    db: AsyncSession,
    *,
    org_name: str = "Test Org",
    app_name: str = "Test App",
    slug: str = "test-app",
    brand: Brand = Brand.HUMANA,
    status: ScanRunStatus = ScanRunStatus.PENDING,
    scanned_at: datetime | None = None,
) -> ScanRun:
    app = await make_app_with_org_unit(db, org_name=org_name, app_name=app_name, slug=slug, brand=brand)
    return await make_scan_run(db, app_id=app.id, status=status, scanned_at=scanned_at)


async def make_score_snapshot(
    db: AsyncSession,
    *,
    app_id: int | None = None,
    scan_run_id: int | None = None,
    org_unit_id: int | None = None,
    score: float = 0.8,
    total_violations: int = 5,
    pages_with_violations: int = 2,
    pages_with_critical_violations: int = 1,
    total_pages: int = 10,
    snapshot_at: datetime | None = None,
) -> ScoreSnapshot:
    snapshot = build_snapshot(
        score=score,
        total_violations=total_violations,
        total_pages=total_pages,
        pages_with_violations=pages_with_violations,
        pages_with_critical_violations=pages_with_critical_violations,
        snapshot_at=snapshot_at or datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
        app_id=app_id,
        scan_run_id=scan_run_id,
        org_unit_id=org_unit_id,
    )
    db.add(snapshot)
    await db.flush()
    return snapshot


async def make_page_result(
    db: AsyncSession,
    *,
    scan_run_id: int,
    url: str = "https://example.com",
) -> PageResult:
    page_result = PageResult(
        scan_run_id=scan_run_id,
        url=url,
        raw_json={},
        passes_count=0,
        inapplicable_count=0,
    )
    db.add(page_result)
    await db.flush()
    return page_result


async def make_rule_finding(
    db: AsyncSession,
    *,
    page_result_id: int,
    rule_id: str = "color-contrast",
    finding_type: FindingType = FindingType.VIOLATION,
    impact: Impact = Impact.SERIOUS,
    category: str | None = "color",
    wcag_criterion: str | None = "1.4.3",
    classifications: list[dict[str, str]] | None = None,
    tags: list[str] | None = None,
) -> RuleFinding:
    rf = RuleFinding(
        page_result_id=page_result_id,
        rule_id=rule_id,
        type=finding_type,
        impact=impact,
        description=f"{rule_id} description",
        help=f"{rule_id} help",
        help_url=f"https://example.com/{rule_id}",
        category=category,
        wcag_criterion=wcag_criterion,
        classifications=classifications or [{"standard": "wcag", "version": "2.0", "level": "AA"}],
        tags=tags or ["wcag2aa", "cat.color"],
    )
    db.add(rf)
    await db.flush()
    return rf


async def make_node_finding(
    db: AsyncSession,
    *,
    rule_finding_id: int,
    html: str = "<div></div>",
    target: list[str] | None = None,
    impact: Impact = Impact.SERIOUS,
    failure_summary: str | None = "Fix this element",
    checks: dict[str, Any] | None = None,
) -> NodeFinding:
    nf = NodeFinding(
        rule_finding_id=rule_finding_id,
        html=html,
        target=target or ["div"],
        impact=impact,
        failure_summary=failure_summary,
        checks=checks or {"any": [], "all": [], "none": []},
    )
    db.add(nf)
    await db.flush()
    return nf


async def latest_ou_snapshot(db: AsyncSession, org_unit_id: int) -> ScoreSnapshot:
    result = await db.execute(
        select(ScoreSnapshot).where(ScoreSnapshot.org_unit_id == org_unit_id).order_by(ScoreSnapshot.id.desc()).limit(1)
    )
    return result.scalar_one()


def make_violation(rule_id: str, impact: str) -> dict[str, Any]:
    return {
        "id": rule_id,
        "impact": impact,
        "description": f"{rule_id} desc",
        "help": f"{rule_id} help",
        "helpUrl": f"https://example.com/{rule_id}",
        "tags": ["best-practice"],
        "nodes": [
            {
                "html": "<div></div>",
                "target": ["div"],
                "impact": impact,
                "any": [],
                "all": [],
                "none": [],
            }
        ],
    }


def make_axe_payload(
    *,
    url: str = "https://example.com",
    violations: Any = None,
    incomplete: Any = None,
) -> dict[str, Any]:
    findings: dict[str, Any] = {
        "violations": violations if violations is not None else [],
        "incomplete": incomplete if incomplete is not None else [],
        "passes": [],
        "inapplicable": [],
    }
    return {"testSubject": {"fileName": url}, "findings": findings}


def parse_axe_payload(
    *,
    url: str = "https://example.com",
    violations: Any = None,
    incomplete: Any = None,
) -> tuple[AxePayload, dict[str, Any]]:
    raw = make_axe_payload(url=url, violations=violations, incomplete=incomplete)
    return AxePayload.model_validate(raw), raw
