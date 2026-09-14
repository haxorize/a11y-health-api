"""The downgrade floor is a real revision, and it is never the head.

`make migrate-roundtrip` upgrades, downgrades to `DOWNGRADE_FLOOR`, and
upgrades again. A floor equal to the head makes the downgrade a no-op, so the
stage becomes a bare `upgrade head` — which the test job already does — while
CI still reports a green `Migration roundtrip` and three documents still
describe it as proof that the revisions above the floor reverse. The floor sat
at the head for exactly that reason once, so this reads the value rather than
trusting it.

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
    heads = _script_directory().get_heads()
    assert len(heads) == 1, f"expected a single head, found {heads}"
    assert floor != heads[0], (
        f"DOWNGRADE_FLOOR is {floor}, which is the head. The roundtrip then downgrades "
        f"across no revisions and proves nothing. Lower the floor to the deepest revision "
        f"whose downgrade cannot undo its upgrade; the Makefile comment carries the rule."
    )
