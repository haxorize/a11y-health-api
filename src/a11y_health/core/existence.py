"""The Existence Guard: every check that a referenced entity exists.

`get_by_pk()` and `get_by_query()` are the only two ways the app asks "does it
exist?", and this module is the only place a `NotFoundError` is built:
`not_found()` hands one to a write whose reference is deleted after the check,
which the Integrity Guard raises (ADR 0048). Entity services keep one-line
accessors delegating here for endpoints; every other module calls the guard
directly instead of importing a sibling service. The six accessors are
`get_app`, `get_app_by_slug`, `get_brand`, `get_org_unit`, `get_scan_run`, and
`get_finding`.

See `docs/architecture.md` ("The Existence Guard and the two-tier call rule").
"""

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import ENTITY_LABELS, Labeled, NotFoundError


def _require_label(model: type) -> None:
    # Checked before the fetch, so an unlabeled model fails on its first
    # guarded call rather than on its first miss in production.
    if model not in ENTITY_LABELS:
        raise KeyError(f"{model.__name__} has no ENTITY_LABELS entry")


def not_found(model: type[Labeled], resource_id: object) -> NotFoundError:
    """The error a write maps a foreign-key violation to through the Integrity
    Guard, when the entity it references is deleted after its check here."""
    _require_label(model)
    return NotFoundError(model, resource_id)


def _require(entity: Labeled | None, model: type[Labeled], resource_id: object) -> Labeled:
    if entity is None:
        raise not_found(model, resource_id)
    return entity


async def get_by_pk(session: AsyncSession, model: type[Labeled], resource_id: object) -> Labeled:
    _require_label(model)
    return _require(await session.get(model, resource_id), model, resource_id)


async def get_by_query(
    session: AsyncSession, model: type[Labeled], stmt: Select[tuple[Labeled]], resource_id: object
) -> Labeled:
    _require_label(model)
    result = await session.execute(stmt)
    return _require(result.scalar_one_or_none(), model, resource_id)
