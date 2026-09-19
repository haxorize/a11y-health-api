"""ADR 0046's two behavioral claims, driven against a scratch repository.

The record says the pre-commit run measures the commit being made and not the
working tree around it, and that the design cannot lose the developer's work.
Both were untestable while the logic lived inline in `.githooks/pre-commit`:
checking either meant making real commits here and reading what happened, which
is not a check anyone runs. `scripts/staged_worktree.sh` is that half of the
hook extracted, and this drives it over a repository built per test.

Every test here shells out to git. Nothing touches this repo — `tmp_path` is
the whole world each one sees.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "staged_worktree.sh"


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with one commit, one staged edit, one unstaged edit, and one
    untracked file — the four states the hook has to tell apart.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--quiet")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")

    (repo / "tracked.txt").write_text("committed\n")
    (repo / "untouched.txt").write_text("untouched\n")
    _git(repo, "add", "tracked.txt", "untouched.txt")
    _git(repo, "commit", "--quiet", "-m", "base")

    # Staged, then edited again on top without staging: the staged half says
    # "staged" and the working tree says "unstaged".
    (repo / "tracked.txt").write_text("staged\n")
    (repo / "added.txt").write_text("added and staged\n")
    _git(repo, "add", "tracked.txt", "added.txt")
    (repo / "tracked.txt").write_text("unstaged\n")

    (repo / "untracked.txt").write_text("never staged\n")
    return repo


def _build(repo: Path, tmp_path: Path) -> Path:
    worktree = tmp_path / "wt"
    subprocess.run(
        [str(_SCRIPT), ".git/index", str(tmp_path / "index-copy"), str(worktree)],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return worktree


def test_the_checkout_holds_the_staged_content_not_the_working_tree(repo: Path, tmp_path: Path) -> None:
    worktree = _build(repo, tmp_path)

    # The claim in one assertion: the file says "staged" in the checkout while
    # it says "unstaged" on disk beside it.
    assert (worktree / "tracked.txt").read_text() == "staged\n"
    assert (repo / "tracked.txt").read_text() == "unstaged\n"


def test_a_staged_addition_reaches_the_checkout(repo: Path, tmp_path: Path) -> None:
    worktree = _build(repo, tmp_path)

    assert (worktree / "added.txt").read_text() == "added and staged\n"


def test_an_untracked_file_stays_out_of_the_checkout(repo: Path, tmp_path: Path) -> None:
    worktree = _build(repo, tmp_path)

    # The rejected "revert and restore" design failed exactly here: an untracked
    # module a committed file imports would still have carried the run.
    assert not (worktree / "untracked.txt").exists()
    assert (repo / "untracked.txt").exists()


def test_the_working_tree_is_byte_identical_afterwards(repo: Path, tmp_path: Path) -> None:
    before = {path.name: path.read_bytes() for path in sorted(repo.glob("*.txt"))}
    assert before, "the fixture wrote no files, so this compares nothing"

    _build(repo, tmp_path)

    after = {path.name: path.read_bytes() for path in sorted(repo.glob("*.txt"))}
    assert after == before


def test_the_real_index_is_never_written(repo: Path, tmp_path: Path) -> None:
    index = repo / ".git" / "index"
    before = index.read_bytes()
    staged_before = _git(repo, "diff", "--cached", "--name-status")

    _build(repo, tmp_path)

    assert index.read_bytes() == before, "the developer's index file changed"
    assert _git(repo, "diff", "--cached", "--name-status") == staged_before


def test_the_checkout_is_detached_and_leaves_the_branch_alone(repo: Path, tmp_path: Path) -> None:
    head_before = _git(repo, "rev-parse", "HEAD").strip()
    branch_before = _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip()

    _build(repo, tmp_path)

    assert _git(repo, "rev-parse", "HEAD").strip() == head_before
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip() == branch_before


def test_it_reads_the_index_git_names_rather_than_always_dot_git_index(repo: Path, tmp_path: Path) -> None:
    # `git commit -a` and `git commit <paths>` build the tree in a lock file
    # beside .git/index and hand the hook its path. Passing a different index
    # has to produce a different checkout, or the hook is measuring the wrong
    # one in both of those shapes.
    alternate = tmp_path / "alternate-index"
    shutil.copy(repo / ".git" / "index", alternate)
    subprocess.run(
        ["git", "-C", str(repo), "add", "untracked.txt"],
        check=True,
        capture_output=True,
        env={"GIT_INDEX_FILE": str(alternate), "PATH": "/usr/bin:/bin:/usr/local/bin", "HOME": str(tmp_path)},
    )

    worktree = tmp_path / "wt-alt"
    subprocess.run(
        [str(_SCRIPT), str(alternate), str(tmp_path / "index-copy-alt"), str(worktree)],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    assert (worktree / "untracked.txt").exists(), "the alternate index was ignored"
    assert not (_build(repo, tmp_path) / "untracked.txt").exists(), "the default index should not have it"


def test_a_missing_index_is_refused_rather_than_producing_an_empty_checkout(repo: Path, tmp_path: Path) -> None:
    result = subprocess.run(
        [str(_SCRIPT), str(tmp_path / "no-such-index"), str(tmp_path / "copy"), str(tmp_path / "wt")],
        cwd=repo,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "no index at" in result.stderr
