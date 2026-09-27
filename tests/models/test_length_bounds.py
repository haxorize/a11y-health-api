from collections.abc import Awaitable, Callable

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.slug import NAME_MAX_LENGTH, SLUG_MAX_LENGTH
from a11y_health.models.app import CK_APP_NAME_LENGTH, CK_APP_SLUG_LENGTH
from a11y_health.models.brand import CK_BRAND_NAME_LENGTH
from a11y_health.models.org_unit import CK_ORG_UNIT_NAME_LENGTH
from tests.factories import make_app_with_org_unit, make_brand, make_org_unit

_BOUNDS = [
    pytest.param(make_app_with_org_unit, "name", CK_APP_NAME_LENGTH, NAME_MAX_LENGTH, id="app-name"),
    pytest.param(make_app_with_org_unit, "slug", CK_APP_SLUG_LENGTH, SLUG_MAX_LENGTH, id="app-slug"),
    pytest.param(make_brand, "name", CK_BRAND_NAME_LENGTH, NAME_MAX_LENGTH, id="brand-name"),
    pytest.param(make_org_unit, "name", CK_ORG_UNIT_NAME_LENGTH, NAME_MAX_LENGTH, id="org-unit-name"),
]


@pytest.mark.parametrize(("make_row", "column", "constraint", "bound"), _BOUNDS)
async def test_the_constraint_admits_the_bound_and_refuses_one_past_it(
    db_session: AsyncSession,
    make_row: Callable[[AsyncSession], Awaitable[object]],
    column: str,
    constraint: str,
    bound: int,
) -> None:
    # Red when the constant moves and a model's constraint does not.
    row = await make_row(db_session)
    setattr(row, column, "a" * bound)
    await db_session.flush()

    with pytest.raises(IntegrityError, match=constraint):
        async with db_session.begin_nested():
            setattr(row, column, "a" * (bound + 1))
            await db_session.flush()
