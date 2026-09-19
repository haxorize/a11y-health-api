#!/usr/bin/env bash
set -euo pipefail

# The roundtrip runs against a scratch database created and dropped around it,
# never against DATABASE_URL. Its last command upgrades back to head, and the
# head's upgrade() re-runs a data-repair DELETE its own downgrade() does not
# restore — so the same three alembic commands aimed at a developer's seeded
# database remove rollup snapshots without a word, and `make migrate-roundtrip`
# is step 3 of every model change, so that is the documented path, not a misuse
# of it. The floor itself is downgraded *to* and never crossed.
#
# Connection comes from the PG* variables psql and libpq already read, so CI's
# service container works by setting them on the job and a developer needs
# nothing. DATABASE_URL is not consulted: its database name is the one thing
# this script must not use.

# Run directly rather than through `make migrate-roundtrip`, this inherits no
# UV_LOCKED from the Makefile's export, and a migration checked against a
# dependency set CI never resolves is checked against the wrong one.
export UV_LOCKED=1

FLOOR="${1:?usage: migrate_roundtrip.sh <downgrade-floor>}"

# Minted here, never taken from the caller. It was parameter 2, and the usage
# string is this script's whole interface to the agents and CI that drive it —
# so `migrate_roundtrip.sh <floor> a11y_health` was one obvious reading away,
# and it drops the developer's seeded database before the first alembic
# command and again on the way out.
#
# Per-pid because the other two shared resources this tooling isolates are
# (the hook's temp paths, the suite's test database), and two developers
# against one Postgres would otherwise drop each other's scratch mid-upgrade.
# The cost is that a hard-killed run orphans its database where a fixed name
# reclaimed itself next run: `DROP DATABASE a11y_health_roundtrip_<pid>` by
# hand, or psql -l to find them.
SCRATCH="a11y_health_roundtrip_$$"

export PGHOST="${PGHOST:-localhost}"
export PGPORT="${PGPORT:-5432}"

# The URL alembic gets has to carry the same credentials psql just used, and
# libpq's defaults (peer auth, no user in the URL) are not expressible as a
# userinfo section — so it is built only when PGUSER is actually set.
#
# Percent-encoded, not concatenated. libpq never sees a URL, so `@` and `/` are
# ordinary password characters to it; spliced raw into one, `p@ss/word` parses
# as host `ss` and database `word@localhost:5432/...` with no exception and no
# warning, and only the alembic leg is aimed at the wrong place — psql read
# PGPASSWORD directly and succeeded moments earlier.
urlencode() {
  local s="$1" out="" i c
  for (( i = 0; i < ${#s}; i++ )); do
    c="${s:i:1}"
    case "$c" in
      [a-zA-Z0-9.~_-]) out="$out$c" ;;
      *) printf -v c '%%%02X' "'$c"; out="$out$c" ;;
    esac
  done
  printf '%s' "$out"
}

userinfo=""
if [ -n "${PGUSER:-}" ]; then
  userinfo="$(urlencode "$PGUSER")"
  [ -n "${PGPASSWORD:-}" ] && userinfo="$userinfo:$(urlencode "$PGPASSWORD")"
  userinfo="$userinfo@"
fi

drop_scratch() {
  psql -q -d postgres -c "DROP DATABASE IF EXISTS $SCRATCH;" >/dev/null
}
# `|| true` on the trap only. Bash propagates a failing EXIT-trap body into the
# script's status, so a backend still attached when DROP DATABASE fires would
# report the roundtrip red after all three alembic commands had succeeded. The
# call below is a precondition, not teardown, and stays strict.
trap 'drop_scratch || true' EXIT

drop_scratch
psql -q -d postgres -c "CREATE DATABASE $SCRATCH;" >/dev/null

export DATABASE_URL="postgresql+asyncpg://${userinfo}${PGHOST}:${PGPORT}/${SCRATCH}"
uv run alembic upgrade head
uv run alembic downgrade "$FLOOR"
uv run alembic upgrade head
