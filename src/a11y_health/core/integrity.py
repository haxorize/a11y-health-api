"""Guarded flush: translate recognized constraint violations into domain errors.

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

    The mutation must happen inside the `async with` block, not before it:
    `begin_nested()` flushes pending state *before* emitting SAVEPOINT
    (`SessionTransaction._take_snapshot`), so a write pending at entry would
    fail outside the savepoint and poison the whole transaction. A violation
    raised by that entry pre-flush is never classified — it re-raises raw, so
    misuse fails loudly instead of surfacing a mapped error the savepoint
    can't back.

    Mapping values are single-use: `raise ... from` mutates the instance it
    raises (`__cause__`, `__traceback__`), so build the mapping per call —
    never hoist one to module level, where a raised instance would carry state
    across requests.
    """
    engaged = False
    try:
        async with session.begin_nested():
            engaged = True
            yield
            await session.flush()
    except IntegrityError as exc:
        if not engaged:
            raise
        # asyncpg parses the violated constraint's name out of the server
        # error. Matching that identity exactly — never a rendered message,
        # which appends bound row values — means data containing a constraint's
        # name cannot misclassify an unrelated violation, and one constraint
        # name embedded in another cannot collide. Absent attribute
        # (non-constraint failure) → re-raise.
        cause = exc.orig.__cause__ if exc.orig is not None else None
        violated = getattr(cause, "constraint_name", None)
        if isinstance(violated, str) and violated in constraint_errors:
            raise constraint_errors[violated] from exc
        raise
