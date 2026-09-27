---
name: verify
description: Build, launch, and drive a live dev server of this API against a scratch database, so a change is checked end-to-end rather than only under pytest. Use when asked to run, start, launch, or drive the API, when confirming a change works against a real server and a real Postgres, or when a test passes and the question is whether the running thing agrees.
---

# Verifying a change end-to-end

Postgres must be up at `localhost:5432` (`pg_isready`). Use a scratch database so dev data stays untouched:

```bash
psql -h localhost -d postgres -c "DROP DATABASE IF EXISTS a11y_health_verify;" -c "CREATE DATABASE a11y_health_verify;"
DATABASE_URL="postgresql+asyncpg://localhost:5432/a11y_health_verify" uv run alembic upgrade head
DATABASE_URL="postgresql+asyncpg://localhost:5432/a11y_health_verify" uv run uvicorn a11y_health.main:app --port 8055 --log-level warning  # background
```

The server is up when `curl -s localhost:8055/api/v1/health` returns `{"status":"healthy"}`.

## Drive it

The onboarding CLI is the drive step. It issues the same calls a hand-written `httpx` script would, so reach for a script only where the change is in a surface the CLI never touches. When you do write one, build the Axe Payload with `make_axe_payload`/`make_violation` from `tests/factories.py` rather than by hand: every violation needs a `cat.*` tag, and one without it is refused at the Axe Boundary with a 400 (`schemas/axe_payload.py`, `No category tag found`). Read flags from `uv run a11y <command> --help`; the sequence below is what a fresh scratch database needs, in order:

```bash
uv run a11y org-units list --base-url http://localhost:8055
uv run a11y brands list --base-url http://localhost:8055
uv run a11y org-units create "Verify Team" --parent-id 1 --base-url http://localhost:8055   # → id 2
mkdir -p /tmp/verify-scans/2026-03-30 && cp tests/fixtures/*.json /tmp/verify-scans/2026-03-30/
uv run a11y import /tmp/verify-scans --org-unit-id 2 --brand-id 1 --base-url http://localhost:8055
uv run a11y ingest tests/fixtures --base-url http://localhost:8055
```

**`import` before `ingest`, on a fresh database.** `import` creates the App when it is absent; `ingest` only resolves an existing one by the Slug derived from the JSON `name`, so it fails first on an empty database. The two take different directory shapes: `import` wants a tree of `YYYY-MM-DD` subdirectories, each one a Scan Directory, while `ingest` wants a single Scan Directory — which is what `tests/fixtures/` already is, so the `mkdir`/`cp` above is only there to give `import` its dated tree.

Either command completes the Scan Run, which triggers scoring and then the Org Unit Rollup and the Brand Rollup. Read all three back — `owner_type=app` is the App's own score and shows neither rollup fired:

```bash
curl -s "localhost:8055/api/v1/scores/latest?owner_type=app"
curl -s "localhost:8055/api/v1/scores/latest?owner_type=org_unit"
curl -s "localhost:8055/api/v1/scores/latest?owner_type=brand"
```

Drop the database and kill the server when done.

## Gotchas

- **Brands are seeded by migrations** (Humana=1, CenterWell, Go365, CarePlus, Reliance) and are API-read-only — no POST /brands.
- **Single-root Org Unit invariant**: at most one parentless org unit (none before onboarding, or once the Root Org Unit is deleted); create children under the existing Root Org Unit (`GET /api/v1/org-units` returns a plain list, not a Page).
- Table names are singular (`brand`, `org_unit`, `score_snapshot`) for direct psql seeding/inspection.
