import itertools
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from httpx import Response
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.models.app import App
from a11y_health.models.brand import Brand
from a11y_health.models.classification import Classification
from a11y_health.models.enums import Category, FindingType, Impact, ScanRunStatus, ScoreSnapshotOwnerType
from a11y_health.models.node_finding import NodeFinding
from a11y_health.models.org_unit import OrgUnit
from a11y_health.models.page_result import PageResult
from a11y_health.models.rule_finding import RuleFinding
from a11y_health.models.scan_run import ScanRun
from a11y_health.models.score_snapshot import ScoreSnapshot
from a11y_health.services import org_unit as org_unit_service
from a11y_health.services import owner as owner_service
from a11y_health.services.owner import ChildrenRead, ScoreAggregates, owned
from a11y_health.services.page_result import create_page_result
from a11y_health.services.scan_run import get_scan_run
from a11y_health.services.score_snapshot import compute_app_score

SessionFactory = Callable[[], AsyncSession]

DEFAULT_SNAPSHOT_AT = datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC)


async def make_org_unit(db: AsyncSession, *, name: str = "Test Org", parent_id: int | None = None) -> OrgUnit:
    org_unit = OrgUnit(name=name, parent_id=parent_id)
    db.add(org_unit)
    await db.flush()
    return org_unit


_brand_seq = itertools.count(1)


async def make_brand(db: AsyncSession, *, name: str | None = None) -> Brand:
    if name is None:
        name = f"Test Brand {next(_brand_seq)}"
    brand = Brand(name=name)
    db.add(brand)
    await db.flush()
    return brand


async def make_app(
    db: AsyncSession,
    *,
    name: str = "Test App",
    slug: str = "test-app",
    brand_id: int | None = None,
    org_unit_id: int,
) -> App:
    if brand_id is None:
        brand = await make_brand(db)
        brand_id = brand.id
    app = App(name=name, slug=slug, brand_id=brand_id, org_unit_id=org_unit_id)
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
        scanned_at=DEFAULT_SNAPSHOT_AT if scanned_at is None else scanned_at,
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
    brand_id: int | None = None,
) -> App:
    # Nest under the existing root when one exists — a second parentless org
    # unit would violate the single-root index (ADR 0026).
    existing_root_id = await org_unit_service.get_root_id(db)
    org_unit = await make_org_unit(db, name=org_name, parent_id=existing_root_id)
    return await make_app(db, name=app_name, slug=slug, brand_id=brand_id, org_unit_id=org_unit.id)


async def make_scan_run_with_parents(
    db: AsyncSession,
    *,
    org_name: str = "Test Org",
    app_name: str = "Test App",
    slug: str = "test-app",
    brand_id: int | None = None,
    status: ScanRunStatus = ScanRunStatus.PENDING,
    scanned_at: datetime | None = None,
) -> ScanRun:
    app = await make_app_with_org_unit(db, org_name=org_name, app_name=app_name, slug=slug, brand_id=brand_id)
    return await make_scan_run(db, app_id=app.id, status=status, scanned_at=scanned_at)


# The one home of the snapshot aggregate defaults, beside DEFAULT_SNAPSHOT_AT
# for observation time: both snapshot factories read their keyword defaults
# off it, and a test that has to build a raw `ScoreSnapshot` row (one
# `owned()` cannot express) spreads `DEFAULT_SCORE_AGGREGATES._asdict()` in
# beside `snapshot_at=DEFAULT_SNAPSHOT_AT`.
DEFAULT_SCORE_AGGREGATES = ScoreAggregates(
    score=0.8,
    total_violations=5,
    pages_with_violations=2,
    pages_with_critical_violations=1,
    total_pages=10,
)


def build_score_snapshot(
    *,
    owner_type: ScoreSnapshotOwnerType,
    owner_id: int,
    scan_run_id: int | None = None,
    score: float = DEFAULT_SCORE_AGGREGATES.score,
    total_violations: int = DEFAULT_SCORE_AGGREGATES.total_violations,
    total_pages: int = DEFAULT_SCORE_AGGREGATES.total_pages,
    pages_with_violations: int = DEFAULT_SCORE_AGGREGATES.pages_with_violations,
    pages_with_critical_violations: int = DEFAULT_SCORE_AGGREGATES.pages_with_critical_violations,
    snapshot_at: datetime = DEFAULT_SNAPSHOT_AT,
) -> ScoreSnapshot:
    # Nothing is persisted: a test that needs a snapshot the database never
    # sees calls this, and make_score_snapshot delegates through it.
    aggregates = ScoreAggregates(
        score=score,
        total_violations=total_violations,
        total_pages=total_pages,
        pages_with_violations=pages_with_violations,
        pages_with_critical_violations=pages_with_critical_violations,
    )
    return owned(owner_type, owner_id, aggregates, scan_run_id=scan_run_id, snapshot_at=snapshot_at)


async def make_score_snapshot(
    db: AsyncSession,
    *,
    app_id: int | None = None,
    org_unit_id: int | None = None,
    brand_id: int | None = None,
    scan_run_id: int | None = None,
    score: float = DEFAULT_SCORE_AGGREGATES.score,
    total_violations: int = DEFAULT_SCORE_AGGREGATES.total_violations,
    total_pages: int = DEFAULT_SCORE_AGGREGATES.total_pages,
    pages_with_violations: int = DEFAULT_SCORE_AGGREGATES.pages_with_violations,
    pages_with_critical_violations: int = DEFAULT_SCORE_AGGREGATES.pages_with_critical_violations,
    snapshot_at: datetime = DEFAULT_SNAPSHOT_AT,
) -> ScoreSnapshot:
    owners = [
        (t, v)
        for t, v in (
            (ScoreSnapshotOwnerType.APP, app_id),
            (ScoreSnapshotOwnerType.ORG_UNIT, org_unit_id),
            (ScoreSnapshotOwnerType.BRAND, brand_id),
        )
        if v is not None
    ]
    if len(owners) != 1:
        raise ValueError("Exactly one of app_id, org_unit_id, brand_id must be set")
    [(owner_type, owner_id)] = owners
    snapshot = build_score_snapshot(
        owner_type=owner_type,
        owner_id=owner_id,
        scan_run_id=scan_run_id,
        score=score,
        total_violations=total_violations,
        total_pages=total_pages,
        pages_with_violations=pages_with_violations,
        pages_with_critical_violations=pages_with_critical_violations,
        snapshot_at=snapshot_at,
    )
    db.add(snapshot)
    await db.flush()
    return snapshot


# Arrange only, and the shared factory never owns a subject: what a test
# invokes after arrange completes (the orchestration handler, a rollup call)
# stays visible at the test's own call site. A new scoring or rollup tail
# means a new helper name, never a mode flag on an existing one.
async def ingest_pages_and_complete(db: AsyncSession, scan_run_id: int, axe_payloads: list[dict]) -> ScanRun:
    for raw in axe_payloads:
        await create_page_result(db, scan_run_id, raw)
    sr = await get_scan_run(db, scan_run_id)
    sr.status = ScanRunStatus.COMPLETED
    await db.flush()
    return sr


async def complete_new_scan_run(
    db: AsyncSession, app_id: int, axe_payloads: list[dict], scanned_at: datetime | None = None
) -> ScanRun:
    sr = await make_scan_run(db, app_id=app_id, scanned_at=scanned_at)
    return await ingest_pages_and_complete(db, sr.id, axe_payloads)


# The final call is the act only for a test whose subject is the score compute
# itself; a rollup test uses this to arrange an already-scored app.
async def ingest_and_score(db: AsyncSession, scan_run_id: int, axe_payloads: list[dict]) -> ScoreSnapshot:
    sr = await ingest_pages_and_complete(db, scan_run_id, axe_payloads)
    return await compute_app_score(db, sr)


# Arrange only, like ingest_and_score: the rollup that reads this snapshot
# stays visible in each test body.
async def score_new_scan_run(
    db: AsyncSession, app_id: int, axe_payloads: list[dict], scanned_at: datetime | None = None
) -> ScoreSnapshot:
    sr = await make_scan_run(db, app_id=app_id, scanned_at=scanned_at)
    return await ingest_and_score(db, sr.id, axe_payloads)


def substitute_children_read(
    mocker, owner_type: ScoreSnapshotOwnerType, wrap: Callable[[ChildrenRead], ChildrenRead]
) -> None:
    """Substitute an owner's rollup children read through the sanctioned seam
    (ADR 0037): swap the whole OWNERS table for the test's duration — consumers
    resolve it at call time. `wrap` receives the real read."""
    spec = owner_service.OWNERS[owner_type]
    assert spec.rollup is not None
    substituted = spec._replace(rollup=spec.rollup._replace(children=wrap(spec.rollup.children)))
    mocker.patch.object(owner_service, "OWNERS", MappingProxyType({**owner_service.OWNERS, owner_type: substituted}))


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


async def make_page_result_with_parents(db: AsyncSession) -> PageResult:
    scan_run = await make_scan_run_with_parents(db)
    return await make_page_result(db, scan_run_id=scan_run.id)


async def make_rule_finding(
    db: AsyncSession,
    *,
    page_result_id: int,
    rule_id: str = "color-contrast",
    finding_type: FindingType = FindingType.VIOLATION,
    impact: Impact = Impact.SERIOUS,
    category: Category = Category.COLOR,
    wcag_criteria: list[str] | None = None,
    classifications: list[Classification | dict[str, Any]] | None = None,
    tags: list[str] | None = None,
) -> RuleFinding:
    # `is None` rather than `or`, so an explicit empty list stays empty.
    if wcag_criteria is None:
        wcag_criteria = ["1.4.3"]
    if classifications is None:
        classifications = [Classification(standard="wcag", version="2.0", level="AA")]
    if tags is None:
        tags = ["wcag2aa", "cat.color"]
    rf = RuleFinding(
        page_result_id=page_result_id,
        rule_id=rule_id,
        type=finding_type,
        impact=impact,
        description=f"{rule_id} description",
        help=f"{rule_id} help",
        help_url=f"https://example.com/{rule_id}",
        category=category,
        wcag_criteria=wcag_criteria,
        classifications=classifications,
        tags=tags,
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
        target=["div"] if target is None else target,
        impact=impact,
        failure_summary=failure_summary,
        checks={"any": [], "all": [], "none": []} if checks is None else checks,
    )
    db.add(nf)
    await db.flush()
    return nf


async def _all_snapshots(db: AsyncSession, filter_col: Any, filter_val: int) -> list[ScoreSnapshot]:
    # Oldest first by Latest Score Snapshot's order (observation time, ties to
    # the higher id), so [-1] is the latest: the readers below take it there,
    # and a test holding the whole list may too.
    result = await db.execute(
        select(ScoreSnapshot).where(filter_col == filter_val).order_by(ScoreSnapshot.snapshot_at, ScoreSnapshot.id)
    )
    return list(result.scalars().all())


async def ou_snapshots(db: AsyncSession, org_unit_id: int) -> list[ScoreSnapshot]:
    return await _all_snapshots(db, ScoreSnapshot.org_unit_id, org_unit_id)


async def brand_snapshots(db: AsyncSession, brand_id: int) -> list[ScoreSnapshot]:
    return await _all_snapshots(db, ScoreSnapshot.brand_id, brand_id)


async def app_snapshots(db: AsyncSession, app_id: int) -> list[ScoreSnapshot]:
    return await _all_snapshots(db, ScoreSnapshot.app_id, app_id)


async def latest_ou_snapshot(db: AsyncSession, org_unit_id: int) -> ScoreSnapshot:
    return (await ou_snapshots(db, org_unit_id))[-1]


async def latest_brand_snapshot(db: AsyncSession, brand_id: int) -> ScoreSnapshot:
    return (await brand_snapshots(db, brand_id))[-1]


async def latest_app_snapshot(db: AsyncSession, app_id: int) -> ScoreSnapshot:
    return (await app_snapshots(db, app_id))[-1]


def make_violation(rule_id: str, impact: str, *, tags: list[str] | None = None) -> dict[str, Any]:
    return {
        "id": rule_id,
        "impact": impact,
        "description": f"{rule_id} desc",
        "help": f"{rule_id} help",
        "helpUrl": f"https://example.com/{rule_id}",
        "tags": tags if tags is not None else ["best-practice", "cat.color"],
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
    name: str = "test-app",
    url: str = "https://example.com",
    violations: Any = None,
    incomplete: Any = None,
    end_time: Any = None,
    unmodeled: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """`end_time` is untyped because several tests hand the boundary values it
    must reject; `None` leaves the key out. `unmodeled` is for keys the schema
    does not model, which the stored Raw JSON must still carry — merged first,
    so it can never shadow a named argument."""
    findings: dict[str, Any] = {
        "violations": violations if violations is not None else [],
        "incomplete": incomplete if incomplete is not None else [],
        "passes": [],
        "inapplicable": [],
    }
    payload: dict[str, Any] = {"name": name, "testSubject": {"fileName": url}, "findings": findings}
    if end_time is not None:
        payload["endTime"] = end_time
    return {**(unmodeled or {}), **payload}


def write_scan_file(
    directory: Path,
    filename: str,
    *,
    name: str,
    url: str = "https://example.com/a",
    end_time: Any = "2026-03-30T11:55:52-0400",
) -> None:
    payload = make_axe_payload(name=name, url=url, end_time=end_time)
    (directory / filename).write_text(json.dumps(payload))


def write_scan_dir(app_dir: Path, date: str, *, name: str, end_time: str | None = None) -> None:
    date_dir = app_dir / date
    date_dir.mkdir()
    # `is not None`, not `or`: an explicit "" is a real case — the axe
    # boundary reads it as absent and the scan falls back to the directory
    # mtime.
    write_scan_file(date_dir, "p.json", name=name, end_time=end_time if end_time is not None else f"{date}T12:00:00Z")


async def advisory_lock_waiters(session: AsyncSession) -> int:
    # pg_locks is instance-wide; without the database filter an unrelated
    # backend's waiter (shared dev/CI instance) would satisfy the poll early.
    result = await session.execute(
        text(
            "SELECT count(*) FROM pg_locks"
            " WHERE locktype = 'advisory' AND NOT granted"
            " AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"
        )
    )
    return result.scalar_one()


def assert_error(response: Response, status: int, code: str, *, message_contains: str | None = None) -> None:
    assert response.status_code == status
    body = response.json()
    assert body["code"] == code
    if message_contains is not None:
        assert message_contains in body["message"].lower()
