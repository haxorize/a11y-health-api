from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.app import App, Brand
from a11y_health.models.org_unit import OrgUnit
from a11y_health.models.page_result import PageResult
from a11y_health.models.rule_finding import FindingType, Impact, RuleFinding
from a11y_health.models.scan_run import ScanRun, ScanRunStatus
from a11y_health.models.score_snapshot import ScoreSnapshot


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
    total_issues: int = 5,
    pages_with_issues: int = 2,
    pages_with_critical_issues: int = 1,
    total_pages: int = 10,
    snapshot_at: datetime | None = None,
) -> ScoreSnapshot:
    snapshot = ScoreSnapshot(
        app_id=app_id,
        scan_run_id=scan_run_id,
        org_unit_id=org_unit_id,
        score=score,
        total_issues=total_issues,
        pages_with_issues=pages_with_issues,
        pages_with_critical_issues=pages_with_critical_issues,
        total_pages=total_pages,
        avg_issues_per_page=total_issues / total_pages if total_pages else 0.0,
        pct_pages_with_issues=pages_with_issues / total_pages if total_pages else 0.0,
        pct_pages_with_critical_issues=pages_with_critical_issues / total_pages if total_pages else 0.0,
        snapshot_at=snapshot_at or datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
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
