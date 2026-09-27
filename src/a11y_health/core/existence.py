"""The Existence Guard: every check that a referenced entity exists.

`get_by_pk()` and `get_by_query()` are the only two ways the application asks
"does it exist?", and this module is the only place a `NotFoundError` is
built. `require_reference()` is `get_by_pk()` for a write: it also returns the
mapping that sends the reference's foreign-key violation, when the entity is
deleted after the check, to the same error through the Integrity Guard (ADR
0048). Entity services keep one-line accessors delegating here for endpoints;
every other module calls the guard directly instead of importing a sibling
service. The six accessors are `get_app`, `get_app_by_slug`, `get_brand`,
`get_org_unit`, `get_scan_run`, and `get_finding`.

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


def _not_found(model: type[Labeled], resource_id: object) -> NotFoundError:
    _require_label(model)
    return NotFoundError(model, resource_id)


def _require(entity: Labeled | None, model: type[Labeled], resource_id: object) -> Labeled:
    if entity is None:
        raise _not_found(model, resource_id)
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


async def require_reference(
    session: AsyncSession, model: type[Labeled], resource_id: object, constraint: str
) -> dict[str, NotFoundError]:
    """The reference check for a write: raise `NotFoundError` if the entity is
    missing, else return `{constraint: <that error>}` for the write's
    `guard_constraints` mapping, which raises it when the entity is deleted
    after this check."""
    await get_by_pk(session, model, resource_id)
    return {constraint: _not_found(model, resource_id)}
