"""A shared skill's copy here matches the hash `skills-sync.lock` records.

Shared skills are authored once in the workspace repo and copied into both
subrepos, with the copy's hash written to this lock (ADR 0001, workspace root).
The rule is that the copy is never edited here — and nothing enforced it: the
lock was committed, the sync script lives in the workspace repo, and neither
the pre-commit hook nor CI invoked anything. Editing the copy and committing
left hook green, CI green, lock stale, and the three copies silently divergent.

This runs in the suite rather than calling `scripts/sync-skills.sh --check`,
because that script is in the parent workspace checkout, which a standalone
clone of this repo and a CI runner both lack. Recomputing the hash needs only
this repo, so the guard runs everywhere the suite does — including inside the
pre-commit hook. It answers "was the copy edited here", which is the forbidden
act; whether the *workspace original* has moved on is still the script's
question, and `scripts/setup.sh` is where that is asked.
"""

import hashlib
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_LOCK = _REPO / "skills-sync.lock"
_SKILLS = _REPO / ".claude" / "skills"


def skill_hash(directory: Path) -> str:
    # Byte-for-byte what sync-skills.sh's skill_hash() computes: every file
    # under the directory as `path NUL size NUL content`, paths relative and
    # `./`-prefixed the way `find .` emits them, sorted bytewise as `LC_ALL=C
    # sort -z` sorts them. A symlinked file is read through, matching its `-L`
    # and the `cp -R` the sync itself does; a symlinked *directory* is not
    # recursed into here, where `find -L` descends it.
    #
    # Walked through git rather than the disk, so a stray `.DS_Store` or an
    # editor swap file beside the copy is not read as an edit to it. A tracked
    # file's contents are still read from the working tree.
    digest = hashlib.sha256()
    files = sorted(
        (p for p in _tracked_files(directory) if p.is_file()),
        key=lambda p: f"./{p.relative_to(directory)}".encode(),
    )
    for path in files:
        content = path.read_bytes()
        digest.update(f"./{path.relative_to(directory)}".encode() + b"\0")
        digest.update(str(len(content)).encode() + b"\0")
        digest.update(content)
    return digest.hexdigest()


def _tracked_files(directory: Path) -> list[Path]:
    listed = subprocess.run(
        ["git", "-C", str(directory), "ls-files", "-z", "--", "."],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [directory / name for name in listed.split("\0") if name]


def locked_skills() -> list[tuple[str, str]]:
    # `(name, recorded_hash)`, the reverse of the lock's own `<sha256>  <name>`
    # column order, so the pairs feed parametrize's ("name", "recorded") ids.
    entries = []
    for line in _LOCK.read_text().splitlines():
        if not line.strip():
            continue
        recorded, name = line.split()
        entries.append((name, recorded))
    return entries


def test_the_lock_names_at_least_one_skill() -> None:
    # Without this, a blanked lock would make the parametrized test below pass
    # by selecting nothing — the zero-ran hole, in the guard that exists to
    # close a hole.
    assert locked_skills(), f"{_LOCK.name} lists no skills; the guard below would check nothing"


@pytest.mark.parametrize(("name", "recorded"), locked_skills())
def test_a_shared_skill_matches_its_recorded_hash(name: str, recorded: str) -> None:
    directory = _SKILLS / name
    assert directory.is_dir(), f"{_LOCK.name} records `{name}`, which is not in .claude/skills/"
    assert skill_hash(directory) == recorded, (
        f"`{name}` differs from the copy `{_LOCK.name}` records. Shared skills are edited at the "
        f"workspace root and synced down (ADR 0001) — revert this copy, make the edit there, and "
        f"run `scripts/sync-skills.sh` from the workspace."
    )
