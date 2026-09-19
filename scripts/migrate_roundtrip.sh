#!/usr/bin/env bash
set -euo pipefail

# The roundtrip runs against a scratch database created and dropped around it,
# never against DATABASE_URL. It downgrades across 8b3a1162eb95, whose
# upgrade() re-runs a data-repair DELETE its downgrade() does not restore, so
# the same three alembic commands aimed at a developer's seeded database would
# remove rollup snapshots without a word, and `make migrate-roundtrip` is step
# 3 of every model change.
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

# Per-pid so two developers against one Postgres cannot drop each other's
# scratch mid-upgrade. A hard-killed run orphans its database; docs/operating.md
# has the cleanup.
SCRATCH="a11y_health_roundtrip_$$"

export PGHOST="${PGHOST:-localhost}"
export PGPORT="${PGPORT:-5432}"

# The URL alembic gets has to carry the same credentials psql just used, and
# libpq's defaults (peer auth, no user in the URL) are not expressible as a
# userinfo section, so it is built only when PGUSER is actually set.
#
# Percent-encoded, not concatenated: spliced raw, `p@ss/word` parses as host
# `ss` with no error, and only the alembic leg is aimed at the wrong place.
# Python rather than bash, which encodes characters instead of UTF-8 bytes and
# does it differently per locale.
urlencode() {
  uv run python -c 'import sys, urllib.parse; print(urllib.parse.quote(sys.argv[1], safe=""), end="")' "$1"
}

userinfo=""
if [ -n "${PGUSER:-}" ]; then
  userinfo="$(urlencode "$PGUSER")"
  [ -n "${PGPASSWORD:-}" ] && userinfo="$userinfo:$(urlencode "$PGPASSWORD")"
  userinfo="$userinfo@"
fi

# WITH (FORCE) terminates any backend still attached, which a bare DROP would
# fail on, so the teardown can stay strict instead of orphaning the database.
drop_scratch() {
  psql -q -d postgres -c "DROP DATABASE IF EXISTS $SCRATCH WITH (FORCE);" >/dev/null
}
trap drop_scratch EXIT

drop_scratch
psql -q -d postgres -c "CREATE DATABASE $SCRATCH;" >/dev/null

export DATABASE_URL="postgresql+asyncpg://${userinfo}${PGHOST}:${PGPORT}/${SCRATCH}"
uv run alembic upgrade head
uv run alembic downgrade "$FLOOR"
uv run alembic upgrade head
