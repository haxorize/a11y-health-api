# Accessibility Health API

A REST API for accessibility health analysis, built with FastAPI, async SQLAlchemy, and Pydantic.

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) package manager
- [gitleaks](https://github.com/gitleaks/gitleaks) on PATH (`brew install gitleaks`) — the pre-commit hook's first stage

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

# Lint (ruff + ty + deptry)
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

Upload a single scan directory as a **Scan Run** to an existing **App**. The **App** is resolved by deriving its **Slug** from the `name` field in the axe DevTools JSON (lowercase ASCII, words joined by hyphens, accents folded — e.g. `My App (Prod)` → `my-app-prod`):

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
```

## Configuration

Configuration is managed via environment variables or a `.env` file:

| Variable | Default | Description |
|---|---|---|
| `DEBUG` | `False` | Enable debug mode |
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
├── core/                   # Deep modules: database, error contract and body,
│                           # existence and integrity guards, pagination, slug
├── models/                 # SQLAlchemy models
├── schemas/                # Pydantic schemas (incl. the axe payload boundary)
├── services/               # Business logic (scoring, rollups, orchestration)
├── cli/                    # Onboarding CLI (errors, scan loading, API client, operations, terminal)
├── config.py               # Settings
└── main.py                 # Application entrypoint
```

Cross-cutting behavior (layering, scoring/rollups, the scan-run lifecycle, pagination, the error contract) is narrated in `docs/architecture.md`; the domain glossary is `DOMAIN.md`; decisions live in `docs/adr/`.
