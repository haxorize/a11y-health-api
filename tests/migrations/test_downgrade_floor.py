"""The downgrade floor is a real revision, and it is never the head.

`make migrate-roundtrip` upgrades, downgrades to `DOWNGRADE_FLOOR`, and
upgrades again. A floor that *resolves* to the head makes the downgrade a
no-op, so the stage becomes a bare `upgrade head` — which the test job already
does — while CI still reports a green `Migration roundtrip` and three documents
still describe it as proof that the revisions above the floor reverse. This
reads the value rather than trusting it, and resolves it before comparing.

Neither check needs a database: both read the Makefile and the revision files.
"""

import re
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

_REPO = Path(__file__).resolve().parents[2]


def _downgrade_floor() -> str:
    # Read from the Makefile rather than restated here: a copy in the suite
    # would be the drift this guard exists to catch, one layer further in.
    makefile = (_REPO / "Makefile").read_text()
    match = re.search(r"^DOWNGRADE_FLOOR := (\w+)$", makefile, re.MULTILINE)
    assert match is not None, "Makefile no longer defines DOWNGRADE_FLOOR as a bare assignment"
    return match.group(1)


def _script_directory() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(_REPO / "alembic.ini")))


def test_the_downgrade_floor_names_a_revision_that_exists() -> None:
    floor = _downgrade_floor()
    assert _script_directory().get_revision(floor) is not None, (
        f"DOWNGRADE_FLOOR is {floor}, which is not a revision in migrations/versions/"
    )


def test_the_downgrade_floor_is_below_the_head() -> None:
    floor = _downgrade_floor()
    script = _script_directory()
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
