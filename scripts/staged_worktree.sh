#!/usr/bin/env bash
set -euo pipefail

# Build a detached checkout of an index, so checks can measure the commit being
# made rather than the working tree around it.
#
# usage: staged_worktree.sh <source-index> <index-copy> <worktree>
#
# Both paths it writes -- the index copy and the worktree -- belong to the
# caller, which is what lets the pre-commit hook reclaim them from a trap and a
# stale-run sweep it already owns. Nothing here touches the caller's working
# tree or their real index; that is the property ADR 0046 rests on, and
# tests/test_staged_worktree.py is what holds it.

SOURCE_INDEX="${1:?usage: staged_worktree.sh <source-index> <index-copy> <worktree>}"
INDEX_COPY="${2:?usage: staged_worktree.sh <source-index> <index-copy> <worktree>}"
WORKTREE="${3:?usage: staged_worktree.sh <source-index> <index-copy> <worktree>}"

trap 'echo "staged_worktree: failed at line $LINENO" >&2' ERR

# Resolved before anything unsets GIT_DIR: `git commit` hands a hook a path
# relative to the repository root, and every git call below runs with a
# different idea of where that is.
ROOT="$(git rev-parse --show-toplevel)"
case "$SOURCE_INDEX" in
  /*) ;;
  *) SOURCE_INDEX="$ROOT/$SOURCE_INDEX" ;;
esac
[ -f "$SOURCE_INDEX" ] || { echo "staged_worktree: no index at $SOURCE_INDEX" >&2; exit 1; }

# git exports these to a hook, and a child inheriting them resolves them
# against the wrong directory once it runs inside the new worktree, where .git
# is a file rather than a directory: `worktree add` dies with "index file open
# failed: Not a directory". Unset here as well as in any caller, because this
# script is also run directly.
unset GIT_INDEX_FILE GIT_DIR GIT_WORK_TREE GIT_PREFIX

cd "$ROOT"

# Through a copy, never in place. The caller's index is the tree they are about
# to commit, and `git write-tree` on it would write index extensions back into
# the real file while `git commit` holds it.
#
# Both paths are refused if they exist rather than cleared: they are arguments,
# and an `rm -rf` on one would delete whatever a caller mistyped. The hook
# sweeps its own stale paths before calling.
for path in "$WORKTREE" "$INDEX_COPY"; do
  if [ -e "$path" ] || [ -L "$path" ]; then
    echo "staged_worktree: $path already exists" >&2
    exit 2
  fi
done
(umask 077 && : >"$INDEX_COPY")
cp "$SOURCE_INDEX" "$INDEX_COPY"

STAGED_TREE="$(GIT_INDEX_FILE="$INDEX_COPY" git write-tree)"
# A commit rather than the bare tree: `worktree add` takes a commit-ish, and
# checking one out seeds the worktree with the staged content -- which is what
# an OpenAPI staleness check regenerates against, so a staged-but-stale spec is
# still caught. The object is unreachable once the worktree is gone, and
# `git gc` reclaims it after `gc.pruneExpire`, two weeks by default.
STAGED_COMMIT="$(git commit-tree "$STAGED_TREE" -m 'pre-commit: staged tree')"

git worktree add --detach --quiet "$WORKTREE" "$STAGED_COMMIT"
