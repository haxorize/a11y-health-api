---
name: verify
description: Build/launch/drive recipe for verifying changes against a live dev server of this API.
---

# Verifying a change end-to-end

Postgres must be up at `localhost:5432` (`pg_isready`). Use a scratch database so dev data stays untouched:

```bash
psql -h localhost -d postgres -c "DROP DATABASE IF EXISTS a11y_health_verify;" -c "CREATE DATABASE a11y_health_verify;"
DATABASE_URL="postgresql+asyncpg://localhost:5432/a11y_health_verify" uv run alembic upgrade head
DATABASE_URL="postgresql+asyncpg://localhost:5432/a11y_health_verify" uv run uvicorn a11y_health.main:app --port 8055 --log-level warning  # background
```

Drive it over HTTP (`httpx` is a project dep; `uv run python <script>`). Drop the database and kill the server when done.

Gotchas:

- **Brands are seeded by migrations** (Humana=1, CenterWell, Go365, CarePlus, Reliance) and are API-read-only — no POST /brands.
- **Single-root Org Unit invariant**: exactly one parentless org unit; create children under the existing root (`GET /api/v1/org-units` returns a plain list, not a Page).
- **Axe payload shape**: `{"name", "testSubject": {"fileName": url}, "findings": {"violations": [...], "incomplete": [], "passes": [], "inapplicable": []}}`. Each violation needs a `cat.*` tag in `tags` or the upload 400s with `invalid_axe_payload` ("No category tag found"). Copy `make_axe_payload`/`make_violation` from `tests/factories.py`.
- **Scan-run lifecycle**: `POST /apps/{id}/scan-runs {"scanned_at": ...}` → `POST /scan-runs/{id}/pages <raw axe payload>` → `PATCH /scan-runs/{id} {"status": "completed"}` (completion triggers scoring + rollups).
- Table names are singular (`brand`, `org_unit`, `score_snapshot`) for direct psql seeding/inspection.
