"""The downgrade floor is a real revision, and it is never the head.

`make migrate-roundtrip` upgrades, downgrades to `DOWNGRADE_FLOOR`, and
upgrades again. A floor that *resolves* to the head makes the downgrade a
no-op, so the stage becomes a bare `upgrade head` — which the test job already
does — while CI still reports a green `Migration roundtrip` and three documents
still describe it as proof that the revisions above the floor reverse. This
reads the value rather than trusting it, and resolves it before comparing.

The checks on the value read only the Makefile and the revision files. The
roundtrip runs against an empty database of its own, and the harness check
holds the migration harness to the same floor, so a test whose world lies
below it is refused at the revision the roundtrip is.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.migrations.harness import (
    IrreversibleRevisionError,
    Roundtrip,
    downgrade_floor,
    restore_world,
    script_directory,
)


def test_the_downgrade_floor_names_a_revision_that_exists() -> None:
    floor = downgrade_floor()
    assert script_directory().get_revision(floor) is not None, (
        f"DOWNGRADE_FLOOR is {floor}, which is not a revision in migrations/versions/"
    )


def test_the_downgrade_floor_is_below_the_head() -> None:
    floor = downgrade_floor()
    script = script_directory()
    heads = script.get_heads()
    assert len(heads) == 1, f"expected a single head, found {heads}"

    # Resolved, not compared as a string. `head`, `heads` and an abbreviated
    # revision id all match the Makefile's `\w+` and all name the head, so a
    # raw comparison passes three spellings of the very failure this catches.
    # The None guard has to precede the `.revision` read: `base` resolves to
    # None rather than raising, and is a legal `alembic downgrade` target.
    resolved = script.get_revision(floor)
    assert resolved is not None, f"DOWNGRADE_FLOOR is {floor}, which names no revision to downgrade to."

    # Counts what the downgrade leg actually crosses: iterate_revisions spans
    # head down to the floor exclusive, so an empty span is a floor that
    # resolves to the head however it was spelled.
    crossed = [rev.revision for rev in script.iterate_revisions(heads[0], resolved.revision)]
    assert crossed, (
        f"DOWNGRADE_FLOOR is {floor}, which resolves to {resolved.revision} — the head. "
        f"The roundtrip then downgrades across no revisions and proves nothing. Set the "
        f"floor to the deepest revision the roundtrip can reach: the shallowest one whose "
        f"downgrade() cannot restore its parent's schema. The Makefile comment carries the rule."
    )


async def test_the_revisions_above_the_floor_reverse(roundtrip: Roundtrip) -> None:
    # What `make migrate-roundtrip` runs; the session's `roundtrip` fixture
    # runs the child, and this is the test that owns its outcome.
    assert roundtrip.returncode == 0, f"the roundtrip failed:\n{roundtrip.stderr}"


async def test_the_harness_stops_at_the_downgrade_floor(db_session: AsyncSession) -> None:
    # The floor is the shallowest revision whose downgrade cannot run, which is
    # the first one a walk from the head toward the base is refused at.
    script = script_directory()
    [root] = script.get_bases()
    floor = script.get_revision(downgrade_floor())
    assert floor is not None
    with pytest.raises(IrreversibleRevisionError) as exc_info:
        await restore_world(db_session, root)
    assert exc_info.value.revision == floor.revision
