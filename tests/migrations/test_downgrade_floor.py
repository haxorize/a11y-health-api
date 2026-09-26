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

import asyncio
import os
import re
import sys
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.migrations.harness import IrreversibleRevisionError, restore_world, script_directory

_REPO = Path(__file__).resolve().parents[2]


def _downgrade_floor() -> str:
    # Read from the Makefile rather than restated here: a copy in the suite
    # would be the drift this guard exists to catch, one layer further in.
    makefile = (_REPO / "Makefile").read_text()
    match = re.search(r"^DOWNGRADE_FLOOR := (\w+)$", makefile, re.MULTILINE)
    assert match is not None, "Makefile no longer defines DOWNGRADE_FLOOR as a bare assignment"
    return match.group(1)


def test_the_downgrade_floor_names_a_revision_that_exists() -> None:
    floor = _downgrade_floor()
    assert script_directory().get_revision(floor) is not None, (
        f"DOWNGRADE_FLOOR is {floor}, which is not a revision in migrations/versions/"
    )


def test_the_downgrade_floor_is_below_the_head() -> None:
    floor = _downgrade_floor()
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


# In a child process because migrations/env.py reads DATABASE_URL at import and
# calls asyncio.run, which this test's running loop forbids. One child for all
# three commands: each extra interpreter costs its imports again, per commit.
_ROUNDTRIP = """
import sys
from alembic import command
from alembic.config import Config

config = Config("alembic.ini")
command.upgrade(config, "head")
command.downgrade(config, sys.argv[1])
command.upgrade(config, "head")
"""


async def test_the_revisions_above_the_floor_reverse(empty_database_url: str) -> None:
    # What `make migrate-roundtrip` runs. Built from the base in a database of
    # its own, never DATABASE_URL: the head's upgrade re-runs a DELETE its
    # downgrade does not restore, so aimed at a developer's database this would
    # remove rollup snapshots without a word.
    child = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        _ROUNDTRIP,
        _downgrade_floor(),
        cwd=_REPO,
        env={**os.environ, "DATABASE_URL": empty_database_url},
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await child.communicate()
    assert child.returncode == 0, f"the roundtrip failed:\n{stderr.decode()}"


async def test_the_harness_stops_at_the_downgrade_floor(db_session: AsyncSession) -> None:
    # The floor is the shallowest revision whose downgrade cannot run, which is
    # the first one a walk from the head toward the base is refused at.
    script = script_directory()
    [root] = script.get_bases()
    floor = script.get_revision(_downgrade_floor())
    assert floor is not None
    with pytest.raises(IrreversibleRevisionError) as exc_info:
        await restore_world(db_session, root)
    assert exc_info.value.revision == floor.revision
