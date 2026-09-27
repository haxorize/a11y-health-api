"""The migration roundtrip: upgrade to the head, downgrade to the Makefile's
`DOWNGRADE_FLOOR`, and upgrade again, in a database of its own that the child
process commits to, outside ADR 0011's rolled-back session.
"""

import asyncio
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def downgrade_floor() -> str:
    # Read from the Makefile rather than restated here: a copy in the suite
    # could drift from the value `make migrate-roundtrip` is documented to use.
    makefile = (_REPO / "Makefile").read_text()
    match = re.search(r"^DOWNGRADE_FLOOR := (\w+)$", makefile, re.MULTILINE)
    assert match is not None, "Makefile no longer defines DOWNGRADE_FLOOR as a bare assignment"
    return match.group(1)


# In a child process because migrations/env.py reads DATABASE_URL at import and
# calls asyncio.run, which the suite's running loop forbids. One child for all
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


@dataclass(frozen=True)
class RoundtripResult:
    # Kept out of the repr: a failed assert prints it, password included.
    database_url: str = field(repr=False)
    returncode: int | None
    stderr: str


async def run_roundtrip(database_url: str) -> RoundtripResult:
    """On a zero `returncode`, leaves the database at the head, reached back up
    from the floor; on any other, wherever the failing command stopped."""
    child = await asyncio.create_subprocess_exec(
        sys.executable,
        "-c",
        _ROUNDTRIP,
        downgrade_floor(),
        cwd=_REPO,
        env={**os.environ, "DATABASE_URL": database_url},
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await child.communicate()
    return RoundtripResult(database_url, child.returncode, stderr.decode())
