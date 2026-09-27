"""The Cursor Pagination conformance sweep over every served operation.

Discovery keys on the response envelope, not on "accepts a cursor": an
operation that loses its cursor must fail the sweep by name, not drop out of
the swept set (Story #94). Bounded reference lists return bare arrays (ADR
0025), so the envelope excludes them naturally. `iter_route_contexts` is the
traversal FastAPI's own OpenAPI generation walks, so the sweep sees every
served operation, not just one router's. `paginate()` itself is tested in
`tests/core/test_pagination.py`.
"""

import functools
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from fastapi.routing import iter_route_contexts

from a11y_health.core.error_contract import ErrorCode
from a11y_health.core.pagination import DEFAULT_PAGE_SIZE, MAX_PAGE_SIZE, Page, PaginationParams, TotaledPage
from a11y_health.main import app
from tests._declaration_honesty import declared_codes


@dataclass(frozen=True)
class _Operation:
    method: str
    context: Any  # the route context: effective declaration and dependant tree
    published: dict[str, Any]  # the operation as the OpenAPI document serves it

    def __str__(self) -> str:
        return f"{self.method} {self.context.path_format}"


def _serves_pages(ctx: Any) -> bool:
    # docs/spec routes are plain starlette Routes with no response_model
    model = getattr(ctx, "response_model", None)
    return isinstance(model, type) and issubclass(model, Page)


@functools.cache
def _spec() -> dict[str, Any]:
    return app.openapi()


@functools.cache
def _paginated_operations() -> tuple[_Operation, ...]:
    operations = []
    for ctx in iter_route_contexts(app.routes):
        if not _serves_pages(ctx):
            continue
        for method in sorted(ctx.methods or ()):
            published = _spec()["paths"].get(ctx.path_format, {}).get(method.lower())
            assert published is not None, (
                f"{method} {ctx.path_format} serves the Page envelope but is missing from the "
                f"OpenAPI document — paginated operations must publish their contract"
            )
            operations.append(_Operation(method, ctx, published))
    assert operations, "paginated-operation sweep found nothing — detection is broken"
    return tuple(operations)


def _flat_dependants(dependant: Any) -> Iterator[Any]:
    yield dependant
    for sub in dependant.dependencies:
        yield from _flat_dependants(sub)


def _published_parameters(op: _Operation) -> dict[str, dict[str, Any]]:
    return {p["name"]: p for p in op.published.get("parameters", [])}


# Asserted against the published spec, not the dependant tree: the wire-level
# `cursor` parameter is what clients rely on, and internal field names can
# diverge from published ones (aliases, model-shaped query params).
def test_every_operation_serving_the_page_envelope_accepts_a_cursor() -> None:
    for op in _paginated_operations():
        assert "cursor" in _published_parameters(op), (
            f"{op} serves the Page envelope but does not accept a cursor — consume PageParams from core.pagination"
        )


# The inverse guard: with envelope ⇒ cursor above and cursor ⇒ envelope here,
# the swept set and the cursor-accepting set stay equal — a hand-rolled cursor
# on a bare-array operation fails by name instead of escaping the sweep.
def test_every_operation_accepting_a_cursor_serves_the_page_envelope() -> None:
    paginated = {(op.context.path_format, op.method.lower()) for op in _paginated_operations()}
    for path, operations in _spec()["paths"].items():
        for method, operation in operations.items():
            if any(param["name"] == "cursor" for param in operation.get("parameters", [])):
                assert (path, method) in paginated, (
                    f"{method.upper()} {path} accepts a cursor but does not serve the Page "
                    f"envelope — unbounded list operations return Page[...] (ADR 0025 keeps "
                    f"bounded reference lists bare and cursor-free)"
                )


def test_every_paginated_operation_uses_the_pagination_owned_definition() -> None:
    for op in _paginated_operations():
        dependants = list(_flat_dependants(op.context.dependant))
        # swept across sub-dependencies too: a shared dependency growing its own
        # limit would publish conflicting schemas for the same wire parameter
        own_params = {
            field.name for dep in dependants if dep.call is not PaginationParams for field in dep.query_params
        }
        assert "cursor" not in own_params and "limit" not in own_params, (
            f"{op} declares pagination parameters outside PageParams — consume PageParams from core.pagination instead"
        )
        assert any(dep.call is PaginationParams for dep in dependants), (
            f"{op} serves the Page envelope but does not consume PageParams from core.pagination"
        )


def test_every_paginated_operation_declares_the_invalid_cursor_mode() -> None:
    for op in _paginated_operations():
        assert ErrorCode.INVALID_CURSOR in declared_codes(op.context), (
            f"{op} serves the Page envelope but does not declare the invalid-cursor error mode — "
            f"add ErrorCode.INVALID_CURSOR to its error_responses()"
        )


# An operation opting into the totaled envelope takes on an obligation, as
# one declaring invalid_cursor does: it must publish `total` as a required
# response property, so a client can rely on it without probing.
def test_every_totaled_operation_publishes_a_required_total() -> None:
    totaled = [op for op in _paginated_operations() if issubclass(op.context.response_model, TotaledPage)]
    assert totaled, "totaled-operation sweep found nothing — detection is broken"
    for op in totaled:
        ref = op.published["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
        schema = _spec()["components"]["schemas"][ref.rsplit("/", 1)[-1]]
        assert "total" in schema.get("required", []), (
            f"{op} serves the TotaledPage envelope but its response schema does not require `total`"
        )


def test_openapi_page_size_bounds_and_default_propagate_from_the_module() -> None:
    for op in _paginated_operations():
        limit = _published_parameters(op).get("limit")
        assert limit is not None, f"{op} serves the Page envelope but publishes no `limit`"
        assert limit["schema"]["minimum"] == 1, f"{op}"
        assert limit["schema"]["maximum"] == MAX_PAGE_SIZE, f"{op}"
        assert limit["schema"]["default"] == DEFAULT_PAGE_SIZE, f"{op}"
