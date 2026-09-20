"""Integrity Guard (DOMAIN.md): turn a recognized constraint violation into
its domain error, with the transaction still usable.

See docs/architecture.md "How errors become HTTP status codes" for how domain
errors reach the wire, and ADR 0028 for the decisions behind this module.
"""

from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core.exceptions import DomainError


@asynccontextmanager
async def guard(
    session: AsyncSession,
    constraint_errors: Mapping[str, DomainError],
) -> AsyncIterator[None]:
    """Run the enclosed mutations and flush them inside a savepoint; on an
    integrity violation of a constraint named in `constraint_errors`, raise the
    mapped domain error with the surrounding transaction still usable. Any
    other violation re-raises unchanged.

    Mutate inside the `async with` block, never before it: a write pending
    at entry fails outside the savepoint, poisons the transaction, and
    re-raises raw rather than mapped.

    Build the mapping per call, never at module level: a raised value carries
    its traceback into whatever raises it next.

    ADR 0028 records the mechanism behind both. The transaction guarantee was
    once silently dead; the diagnosis is
    docs/solutions/begin-nested-flushes-pending-state-before-savepoint.md.
    """
    # Entered outside the try, so a violation raised by the entry pre-flush
    # is never classified.
    async with session.begin_nested():
        try:
            yield
            await session.flush()
        except IntegrityError as exc:
            # asyncpg parses the violated constraint's name out of the
            # server error. Matching that identity exactly — never a rendered
            # message, which appends bound row values — means data containing
            # a constraint's name cannot misclassify an unrelated violation,
            # and one constraint name embedded in another cannot collide.
            # Absent attribute (non-constraint failure) → re-raise.
            cause = exc.orig.__cause__ if exc.orig is not None else None
            violated = getattr(cause, "constraint_name", None)
            if isinstance(violated, str) and violated in constraint_errors:
                raise constraint_errors[violated] from exc
            raise
