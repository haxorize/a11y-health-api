from dataclasses import fields

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.main import app
from a11y_health.models.classification import classifications_in
from a11y_health.schemas.rule_finding import FindingFilters
from tests.factories import (
    make_node_finding,
    make_page_result,
    make_page_result_with_parents,
    make_rule_finding,
    make_scan_run_with_parents,
)
from tests.finding_filter_cases import FILTER_CASES, FilterCase


async def test_list_findings(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page_result = await make_page_result(db_session, scan_run_id=scan_run.id)
    rule_finding = await make_rule_finding(db_session, page_result_id=page_result.id)
    await make_node_finding(db_session, rule_finding_id=rule_finding.id)

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/findings")

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    finding = data["items"][0]
    assert finding["rule_id"] == "color-contrast"
    assert finding["impact"] == "serious"
    assert finding["category"] == "color"
    assert finding["wcag_criteria"] == ["1.4.3"]
    # Deliberately literal — the wire-shape pin for a wcag Classification, like
    # the best-practice pin below; deriving it would tie the assert to the mint
    # under test.
    assert finding["classifications"] == [{"standard": "wcag", "version": "2.0", "level": "AA"}]
    assert finding["node_finding_count"] == 1


# This asserts that `total` crosses the wire; the count semantics are owned by
# the paginate and service suites. total ≠ len(items), so an accidental echo of
# the loaded rows can't pass.
async def test_list_findings_total_counts_beyond_the_page(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page_result = await make_page_result(db_session, scan_run_id=scan_run.id)
    for rule_id in ("color-contrast", "image-alt", "meta-viewport"):
        await make_rule_finding(db_session, page_result_id=page_result.id, rule_id=rule_id)

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/findings", params={"limit": 1})

    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) == 1
    assert data["total"] == 3


async def test_best_practice_classification_serializes_without_null_members(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page_result = await make_page_result(db_session, scan_run_id=scan_run.id)
    rule_finding = await make_rule_finding(
        db_session, page_result_id=page_result.id, classifications=classifications_in(["best-practice"])
    )
    await make_node_finding(db_session, rule_finding_id=rule_finding.id)

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/findings")

    # The wire shape must stay identical to the stored JSONB — explicit null
    # members would break clients generated before Classification was typed.
    assert response.json()["items"][0]["classifications"] == [{"standard": "best-practice"}]


async def test_a_raw_written_null_member_stays_off_the_wire(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page_result = await make_page_result(db_session, scan_run_id=scan_run.id)
    rule_finding = await make_rule_finding(db_session, page_result_id=page_result.id)
    await db_session.execute(
        text("UPDATE rule_finding SET classifications = CAST(:val AS jsonb) WHERE id = :id"),
        {"val": '[{"standard": "best-practice", "version": null}]', "id": rule_finding.id},
    )
    scan_run_id = scan_run.id
    db_session.expire_all()

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run_id}/findings")

    assert response.json()["items"][0]["classifications"] == [{"standard": "best-practice"}]


def test_openapi_declares_typed_classification_schema() -> None:
    schemas = app.openapi()["components"]["schemas"]

    classification = schemas["Classification"]
    assert classification["required"] == ["standard"]
    assert set(classification["properties"]) == {"standard", "version", "level"}
    assert classification["properties"]["standard"]["enum"] == ["wcag", "best-practice"]

    ref = {"$ref": "#/components/schemas/Classification"}
    assert schemas["RuleFindingRead"]["properties"]["classifications"]["items"] == ref
    assert schemas["RuleFindingDetail"]["properties"]["classifications"]["items"] == ref

    # The filter option pairs the query token with the structure it names, so
    # the UI derives labels from the contract instead of its own decode table.
    option = schemas["ClassificationFilterOption"]
    assert option["required"] == ["token", "classification"]
    assert option["properties"]["classification"] == ref
    assert option["properties"]["token"]["enum"] == [
        "wcag2a",
        "wcag2aa",
        "wcag2aaa",
        "wcag21a",
        "wcag21aa",
        "wcag21aaa",
        "wcag22a",
        "wcag22aa",
        "wcag22aaa",
        "best-practice",
    ]
    option_ref = {"$ref": "#/components/schemas/ClassificationFilterOption"}
    assert schemas["FindingFilterOptionsRead"]["properties"]["classifications"]["items"] == option_ref


async def test_list_findings_empty(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/findings")

    assert response.status_code == 200
    data = response.json()
    assert data["items"] == []
    assert data["total"] == 0


async def test_list_findings_scan_run_not_found(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/scan-runs/999/findings")

    assert response.status_code == 404


async def test_filter_options_round_trip(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    await make_rule_finding(db_session, page_result_id=page.id, wcag_criteria=["1.4.3", "1.1.1"])

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/findings/filter-options")

    assert response.status_code == 200
    assert response.json() == {
        "wcag_criteria": ["1.1.1", "1.4.3"],
        "classifications": [
            {"token": "wcag2aa", "classification": {"standard": "wcag", "version": "2.0", "level": "AA"}}
        ],
    }

    # Every enumerated option is accepted by the findings filter it feeds.
    for criterion in response.json()["wcag_criteria"]:
        listing = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/findings", params={"wcag_criterion": criterion})
        assert listing.status_code == 200
        assert listing.json()["items"], f"enumerated criterion {criterion} matched no findings"


async def test_filter_options_serve_classifications_as_token_plus_structure(
    db_client: AsyncClient, db_session: AsyncSession
) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    await make_rule_finding(db_session, page_result_id=page.id, classifications=classifications_in(["wcag21aa"]))
    await make_rule_finding(
        db_session,
        page_result_id=page.id,
        rule_id="image-alt",
        classifications=classifications_in(["best-practice"]),
    )

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/findings/filter-options")

    assert response.status_code == 200
    # Deliberately literal — the wire-shape pin the UI derives labels from
    # (#125), like the classification pins in the listing tests.
    assert response.json()["classifications"] == [
        {"token": "wcag21aa", "classification": {"standard": "wcag", "version": "2.1", "level": "AA"}},
        {"token": "best-practice", "classification": {"standard": "best-practice"}},
    ]

    # Every enumerated token is accepted by the findings filter it feeds.
    for option in response.json()["classifications"]:
        listing = await db_client.get(
            f"/api/v1/scan-runs/{scan_run.id}/findings", params={"classification": option["token"]}
        )
        assert listing.status_code == 200
        assert listing.json()["items"], f"enumerated token {option['token']} matched no findings"


async def test_filter_options_scan_run_not_found(db_client: AsyncClient) -> None:
    response = await db_client.get("/api/v1/scan-runs/999/findings/filter-options")

    assert response.status_code == 404


# Breaks when a dimension is declared with no case, which the decode test below
# would then never send, so nothing proves it reaches the service.
def test_every_declared_filter_dimension_has_a_case() -> None:
    covered: set[str] = set()
    for param in FILTER_CASES:
        case = param.values[0]
        assert isinstance(case, FilterCase)
        covered |= case.dimensions

    assert {f.name for f in fields(FindingFilters)} == covered


# Breaks when a dimension's query parameter is renamed or dropped (the
# non-matching finding comes back), or when a repeated parameter decodes to its
# last value only (the first-value match goes missing; every dimension has a
# case selecting two values).
@pytest.mark.parametrize("case", FILTER_CASES)
async def test_each_filter_parameter_decodes_to_its_dimension(
    db_client: AsyncClient, db_session: AsyncSession, case: FilterCase
) -> None:
    page = await make_page_result_with_parents(db_session)
    kept = await case.seed(db_session, page.id)

    response = await db_client.get(f"/api/v1/scan-runs/{page.scan_run_id}/findings", params=case.query)

    assert response.status_code == 200
    assert {f["rule_id"] for f in response.json()["items"]} == kept


async def test_filter_by_category_invalid_returns_422(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/findings", params={"category": "bogus"})

    assert response.status_code == 422


async def test_get_finding_detail(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)
    page = await make_page_result(db_session, scan_run_id=scan_run.id)
    finding = await make_rule_finding(db_session, page_result_id=page.id)
    node = await make_node_finding(
        db_session,
        rule_finding_id=finding.id,
        html="<span>bad</span>",
        target=[".main > span"],
        failure_summary="Insufficient contrast",
        checks={"any": [{"id": "color-contrast", "data": {}, "message": "low ratio"}], "all": [], "none": []},
    )

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/findings/{finding.id}")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == finding.id
    assert data["rule_id"] == "color-contrast"
    assert len(data["node_findings"]) == 1
    nf = data["node_findings"][0]
    assert nf["id"] == node.id
    assert nf["html"] == "<span>bad</span>"
    assert nf["target"] == [".main > span"]
    assert nf["impact"] == "serious"
    assert nf["failure_summary"] == "Insufficient contrast"
    assert nf["checks"] == {
        "any": [{"id": "color-contrast", "data": {}, "message": "low ratio"}],
        "all": [],
        "none": [],
    }


async def test_get_finding_not_found(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run = await make_scan_run_with_parents(db_session)

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run.id}/findings/999")

    assert response.status_code == 404


async def test_get_finding_wrong_scan_run(db_client: AsyncClient, db_session: AsyncSession) -> None:
    scan_run_1 = await make_scan_run_with_parents(db_session)
    scan_run_2 = await make_scan_run_with_parents(db_session, slug="other-app")
    page = await make_page_result(db_session, scan_run_id=scan_run_1.id)
    finding = await make_rule_finding(db_session, page_result_id=page.id)

    response = await db_client.get(f"/api/v1/scan-runs/{scan_run_2.id}/findings/{finding.id}")

    assert response.status_code == 404
