import pytest
from sqlalchemy.exc import IntegrityError, PendingRollbackError
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import DuplicateRootError
from a11y_health.core.integrity import guard
from a11y_health.models.org_unit import UQ_ORG_UNIT_SINGLE_ROOT, OrgUnit
from tests.factories import make_org_unit


def _root_taken() -> dict[str, DuplicateRootError]:
    # Fresh mapping per test: `raise ... from` mutates the instance it raises.
    return {UQ_ORG_UNIT_SINGLE_ROOT: DuplicateRootError("Org unit")}


async def test_recognized_constraint_raises_mapped_domain_error(db_session: AsyncSession) -> None:
    await make_org_unit(db_session, name="Humana")
    with pytest.raises(DuplicateRootError, match="already exists"):
        async with guard(db_session, _root_taken()):
            db_session.add(OrgUnit(name="Shadow Humana", parent_id=None))


async def test_unrecognized_violation_reraises_unchanged(db_session: AsyncSession) -> None:
    # The parent FK fails, which the mapping doesn't recognize.
    with pytest.raises(IntegrityError):
        async with guard(db_session, _root_taken()):
            db_session.add(OrgUnit(name="Orphan", parent_id=999999))


async def test_row_values_containing_constraint_name_cannot_misclassify(db_session: AsyncSession) -> None:
    # Only the parent FK actually fails here, but the row's name value embeds the
    # mapped constraint's identifier. Classifying from any rendered message (which
    # appends bound parameters) instead of the parsed constraint identity would
    # misreport this unrelated violation as the mapped domain error.
    with pytest.raises(IntegrityError):
        async with guard(db_session, _root_taken()):
            db_session.add(OrgUnit(name=UQ_ORG_UNIT_SINGLE_ROOT, parent_id=999999))


async def test_non_constraint_violation_reraises_unchanged(db_session: AsyncSession) -> None:
    # A NOT NULL failure carries no parsed constraint_name; the fallback must
    # re-raise rather than trip over the absent identity.
    with pytest.raises(IntegrityError):
        async with guard(db_session, _root_taken()):
            db_session.add(OrgUnit(name=None, parent_id=None))  # type: ignore[arg-type]


async def test_transaction_stays_usable_after_caught_violation(db_session: AsyncSession) -> None:
    root = await make_org_unit(db_session, name="Humana")
    with pytest.raises(DuplicateRootError):
        async with guard(db_session, _root_taken()):
            db_session.add(OrgUnit(name="Shadow Humana", parent_id=None))
    child = await make_org_unit(db_session, name="CenterWell", parent_id=root.id)
    assert child.id is not None


async def test_mutation_outside_guard_would_not_be_protected(db_session: AsyncSession) -> None:
    # begin_nested() flushes pending state before the SAVEPOINT exists, so a write
    # added before the guard fails outside it and poisons the transaction. This pins
    # the reason guard() wraps the mutation instead of just the flush — and that the
    # entry pre-flush is never classified: the raw IntegrityError surfaces, not the
    # mapped domain error the dead savepoint couldn't back.
    root = await make_org_unit(db_session, name="Humana")
    db_session.add(OrgUnit(name="Shadow Humana", parent_id=None))
    with pytest.raises(IntegrityError):
        async with guard(db_session, _root_taken()):
            pass
    with pytest.raises(PendingRollbackError):
        await make_org_unit(db_session, name="CenterWell", parent_id=root.id)
