"""The Existence Guard: every check that a referenced entity exists.

`get_by_pk()` and `get_by_query()` are the only two ways the app asks "does it
exist?", and this module is the only raise site for `NotFoundError`. Entity
services keep one-line accessors delegating here for endpoints; every other
module calls the guard directly instead of importing a sibling service.

See `docs/architecture.md` ("The Existence Guard and the two-tier call rule").
"""

from collections.abc import Mapping
from types import MappingProxyType

from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import NotFoundError
from a11y_health.models.app import App
from a11y_health.models.brand import Brand
from a11y_health.models.org_unit import OrgUnit
from a11y_health.models.rule_finding import RuleFinding
from a11y_health.models.scan_run import ScanRun
from a11y_health.models.score_snapshot import ScoreSnapshot

# ScoreSnapshot is only ever guarded as a Scan Run's summary lookup, so that is
# its canonical label. Read-only so the table stays closed at runtime, not just
# by convention. Services' other error modes read their entity's label from
# here too, so an entity is named identically across all its errors.
ENTITY_LABELS: Mapping[type, str] = MappingProxyType(
    {
        App: "App",
        Brand: "Brand",
        OrgUnit: "Org unit",
        ScanRun: "Scan run",
        RuleFinding: "Finding",
        ScoreSnapshot: "Scan run summary",
    }
)


def _require[T](entity: T | None, label: str, resource_id: object) -> T:
    if entity is None:
        raise NotFoundError(label, resource_id)
    return entity


async def get_by_pk[T](session: AsyncSession, model: type[T], resource_id: object) -> T:
    # Label resolution precedes the fetch so an unlabeled model fails on its
    # first guarded call, not its first miss in production.
    label = ENTITY_LABELS[model]
    return _require(await session.get(model, resource_id), label, resource_id)


async def get_by_query[T](session: AsyncSession, model: type[T], stmt: Select[tuple[T]], resource_id: object) -> T:
    label = ENTITY_LABELS[model]
    result = await session.execute(stmt)
    return _require(result.scalar_one_or_none(), label, resource_id)
