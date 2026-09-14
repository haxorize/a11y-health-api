# Accessibility Health API

A REST API for accessibility health analysis, built with FastAPI, async SQLAlchemy, and Pydantic.

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) package manager
- [gitleaks](https://github.com/gitleaks/gitleaks) on PATH (`brew install gitleaks`) — the pre-commit hook's first stage
- `python3` on PATH — the JSON parser the agent-side hooks read their tool payload with. It is a requirement separate from the Python above, because uv manages the project interpreter without putting a `python3` on PATH, and these hooks are wired from outside this repo (see `## Hooks wired from outside this repo` in `CLAUDE.md`). Without it they fail open: `rename-safety.sh` and `review-receipt.sh` allow every command instead of guarding, announcing it on stderr rather than failing.

## Setup

```sh
# Install dependencies
make install

# Copy environment config
cp .env.example .env

# Enable pre-commit hooks
git config core.hooksPath .githooks

# Run the development server
make dev
```

The API will be available at `http://localhost:8000` with interactive docs at `http://localhost:8000/docs` (Swagger UI) and `http://localhost:8000/redoc` (ReDoc).

Every route mounts without authentication, and the docs pages are ungated for the same reason: the deployment is assumed to be reachable from the intranet and from nowhere else. That is a decision with a stated boundary and three triggers that reopen it, recorded in [ADR 0042](docs/adr/0042-no-authentication-on-an-intranet-only-deployment.md).

## Development

```sh
# Run tests
make test

# Run tests with coverage
make coverage

# Lint (ruff check + ruff format --check + ty + deptry); the pre-commit hook
# runs this same target, and CI runs its lint-style / lint-types / lint-deps parts
make lint

# Format code
make format

# Regenerate openapi.json (commit it with any contract change)
make openapi

# Fail if openapi.json is stale relative to the code
make openapi-check

# Clean build artifacts
make clean
```

## CLI

The onboarding CLI (`uv run a11y`) drives the public API over HTTP — no direct database access. Four commands: `ingest`, `import`, `org-units list|create`, and `brands list`.

Upload a single **Scan Directory** as a **Scan Run** to an existing **App**. A **Scan Directory** holds one axe DevTools JSON export per scanned page, and `ingest` loads every `*.json` file directly inside it, in name order — it does not descend into subdirectories, and a directory with no JSON file in it is refused. The **App** is resolved by deriving its **Slug** from the `name` field in the axe DevTools JSON (lowercase ASCII, words joined by hyphens, accents folded — e.g. `My App (Prod)` → `my-app-prod`):

```sh
uv run a11y ingest <directory>
uv run a11y ingest ./scans/humana.com/2026-03-30 --base-url http://localhost:8000
```

Onboard a new **App** from a directory of `YYYY-MM-DD/` subdirectories (auto-creates the app on first import). The JSON `name` field becomes the App's `name`, and the server derives the `slug` from it — the same derivation the CLI uses to resolve existing Apps, so re-importing the same directory always lands on the same App:

```sh
uv run a11y import <directory> --org-unit-id <id> --brand-id <id>
uv run a11y import ./scans/humana.com --org-unit-id 1 --brand-id 1
```

Pass `--name` to choose the App's display name at creation (identity is locked afterward — there is no rename). The override must derive to the same slug as the JSON `name`, so it can prettify casing and punctuation but never change which App the scans resolve to:

```sh
uv run a11y import ./scans/humana.com --org-unit-id 1 --brand-id 1 --name "Humana.com"
```

Look up (or create) the ids that `import` needs without leaving the CLI:

```sh
uv run a11y org-units list                    # id, name, parent per org unit
uv run a11y org-units create "Digital" --parent-id 1
uv run a11y brands list                       # id, name per brand
```

## Migrations

Database migrations are managed with Alembic (async). The database URL is read from app settings, not `alembic.ini`.

```sh
# Run all pending migrations
make migrate

# Create a new migration (autogenerate from model changes)
make migrate-create msg="add users table"

# Roll back the last migration
make migrate-downgrade

# Upgrade, downgrade to DOWNGRADE_FLOOR, and upgrade again — what CI's
# migration-drift job runs to prove the revisions above the floor reverse
make migrate-roundtrip
```

## Configuration

Configuration is managed via environment variables or a `.env` file:

| Variable | Default | Description |
|---|---|---|
| `DEBUG` | `False` | Echoes every SQL statement to the log, and allows a wildcard `*` in `ALLOWED_ORIGINS` |
| `DATABASE_URL` | `postgresql+asyncpg://localhost:5432/a11y_health` | Database connection string |
| `TEST_DATABASE_URL` | `postgresql+asyncpg://localhost:5432/a11y_health_test` | Test database connection string |
| `ALLOWED_ORIGINS` | `["http://localhost:3000"]` | CORS allowed origins (wildcard `*` rejected when `DEBUG=False`) |

## Project Structure

```
src/a11y_health/
├── api/
│   ├── deps.py             # Dependency injection
│   └── v1/
│       ├── endpoints/      # Route handlers
│       └── router.py       # API router
├── core/                   # Deep modules, with the record to read beside each:
│   ├── database.py         # Engine, session factory, ORM base (ADR 0007)
│   ├── error_body.py       # Wire shape of a coded error body (ADR 0022)
│   ├── error_contract.py   # Error mode table: status + Error Code (ADR 0022)
│   ├── exceptions.py       # The DomainError hierarchy the table keys on (ADR 0022)
│   ├── existence.py        # The Existence Guard (ADR 0024)
│   ├── integrity.py        # The Integrity Guard's guarded flush (ADR 0028)
│   ├── pagination.py       # Keyset pagination: params and query (ADR 0017)
│   └── slug.py             # The single source of App Slugs (ADR 0019)
├── models/                 # SQLAlchemy models
├── schemas/                # Pydantic schemas (incl. the axe payload boundary)
├── services/               # Business logic (scoring, rollups, orchestration)
├── cli/                    # Onboarding CLI (errors, scan loading, API client, operations, terminal)
├── config.py               # Settings
└── main.py                 # Application entrypoint
```

Cross-cutting behavior (layering, scoring/rollups, the scan-run lifecycle, pagination, the error contract) is narrated in `docs/architecture.md`; the domain glossary is `DOMAIN.md`; decisions live in `docs/adr/`.
