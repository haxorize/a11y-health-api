"""ADR 0050's sweep over `app.openapi()`, the document clients generate from.

Red when `EntityId` loses either bound, or when a request id site is declared
as a bare `int` or as no integer at all. A site is found by its name, `id` or
`*_id`, at any depth of a request body. A body publishes its bounds as
doubles, so an off-by-one ceiling there rounds to the same value, and
`tests/api/test_out_of_range_ids.py` holds the exact edge instead.
"""

from collections.abc import Iterator
from typing import Any

from a11y_health.main import app
from tests.factories import IDENTITY_CEILING

# A site, its integer leaves, and whether its bounds are published exactly.
Site = tuple[str, list[dict[str, Any]], bool]


def _is_id(name: str) -> bool:
    return name == "id" or name.endswith("_id")


def _resolve(document: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    while "$ref" in schema:
        schema = document["components"]["schemas"][schema["$ref"].removeprefix("#/components/schemas/")]
    return schema


def _arms(schema: dict[str, Any]) -> list[dict[str, Any]]:
    return [*schema.get("anyOf", []), *schema.get("oneOf", []), *schema.get("allOf", [])]


def _integer_leaves(document: dict[str, Any], schema: dict[str, Any]) -> Iterator[dict[str, Any]]:
    schema = _resolve(document, schema)
    for arm in _arms(schema):
        yield from _integer_leaves(document, arm)
    if schema.get("type") == "array":
        yield from _integer_leaves(document, schema["items"])
    if schema.get("type") == "integer":
        yield schema


def _body_sites(document: dict[str, Any], schema: dict[str, Any], where: str, seen: frozenset[str]) -> Iterator[Site]:
    # `seen` stops a self-referencing body schema from walking forever.
    if (ref := schema.get("$ref")) is not None:
        if ref in seen:
            return
        seen |= {ref}
    schema = _resolve(document, schema)
    for arm in _arms(schema):
        yield from _body_sites(document, arm, where, seen)
    if schema.get("type") == "array":
        yield from _body_sites(document, schema["items"], where, seen)
    for name, field in schema.get("properties", {}).items():
        if _is_id(name):
            yield f"{where} {name}", list(_integer_leaves(document, field)), False
        yield from _body_sites(document, field, f"{where} {name}", seen)


def _request_ids(document: dict[str, Any]) -> Iterator[Site]:
    for path, operations in document["paths"].items():
        for method, operation in operations.items():
            where = f"{method.upper()} {path}"
            for parameter in operation.get("parameters", []):
                if _is_id(parameter["name"]):
                    leaves = list(_integer_leaves(document, parameter["schema"]))
                    yield f"{where} {parameter['in']} {parameter['name']}", leaves, True
            body = operation.get("requestBody", {}).get("content", {}).get("application/json")
            if body is not None:
                yield from _body_sites(document, body["schema"], f"{where} body", frozenset())


# FastAPI's Schema model types the bounds as floats, so a body schema publishes
# the ceiling rounded to 2**63; a parameter keeps the exact integer and is held
# to it (ADR 0050).
def _bounded(leaf: dict[str, Any], exact: bool) -> bool:
    ceiling = IDENTITY_CEILING if exact else float(IDENTITY_CEILING)
    return leaf.get("minimum") == 1 and leaf.get("maximum") == ceiling


def test_every_request_id_is_bounded_to_the_identity_range() -> None:
    sites = list(_request_ids(app.openapi()))

    # The walk's floor: one site of each kind it reads, so a walk that stops
    # finding ids cannot pass by finding none.
    assert {
        "GET /api/v1/apps/{app_id} path app_id",
        "GET /api/v1/apps query brand_id",
        "GET /api/v1/scores/latest query under_org_unit_id",
        "POST /api/v1/apps body brand_id",
        "PATCH /api/v1/org-units/{org_unit_id} body parent_id",
    } <= {site for site, _, _ in sites}
    unbounded = sorted(
        site for site, leaves, exact in sites if not leaves or not all(_bounded(leaf, exact) for leaf in leaves)
    )
    assert unbounded == []
