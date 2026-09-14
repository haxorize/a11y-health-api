#!/usr/bin/env bash
set -euo pipefail

# The roundtrip runs against a scratch database created and dropped around it,
# never against DATABASE_URL. Crossing the downgrade floor re-runs a data-repair
# DELETE whose downgrade restores nothing, so the same three alembic commands
# aimed at a developer's own seeded database remove rollup snapshots without a
# word — and `make migrate-roundtrip` is step 3 of every model change, so that
# is the documented path, not a misuse of it.
#
# Connection comes from the PG* variables psql and libpq already read, so CI's
# service container works by setting them on the job and a developer needs
# nothing. DATABASE_URL is not consulted: its database name is the one thing
# this script must not use.

# Run directly rather than through `make migrate-roundtrip`, this inherits no
# UV_LOCKED from the Makefile's export, and a migration checked against a
# dependency set CI never resolves is checked against the wrong one.
export UV_LOCKED=1

FLOOR="${1:?usage: migrate_roundtrip.sh <downgrade-floor> <scratch-db-name>}"
SCRATCH="${2:?usage: migrate_roundtrip.sh <downgrade-floor> <scratch-db-name>}"

export PGHOST="${PGHOST:-localhost}"
export PGPORT="${PGPORT:-5432}"

# The URL alembic gets has to carry the same credentials psql just used, and
# libpq's defaults (peer auth, no user in the URL) are not expressible as a
# userinfo section — so it is built only when PGUSER is actually set.
userinfo=""
if [ -n "${PGUSER:-}" ]; then
  userinfo="$PGUSER"
  [ -n "${PGPASSWORD:-}" ] && userinfo="$userinfo:$PGPASSWORD"
  userinfo="$userinfo@"
fi

drop_scratch() {
  psql -q -d postgres -c "DROP DATABASE IF EXISTS $SCRATCH;" >/dev/null
}
trap drop_scratch EXIT

drop_scratch
psql -q -d postgres -c "CREATE DATABASE $SCRATCH;" >/dev/null

export DATABASE_URL="postgresql+asyncpg://${userinfo}${PGHOST}:${PGPORT}/${SCRATCH}"
uv run alembic upgrade head
uv run alembic downgrade "$FLOOR"
uv run alembic upgrade head
