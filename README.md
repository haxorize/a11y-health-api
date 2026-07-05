# Accessibility Health API

A REST API for accessibility health analysis, built with FastAPI, async SQLAlchemy, and Pydantic.

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) package manager

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

## Development

```sh
# Run tests
make test

# Run tests with coverage
make test-cov

# Lint (ruff + ty)
make lint

# Format code
make format

# Clean build artifacts
make clean
```

## CLI

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
│   ├── deps.py          # Dependency injection
│   └── v1/
│       ├── endpoints/   # Route handlers
│       └── router.py    # API router
├── core/
│   ├── database.py      # Database setup
│   └── exceptions.py    # Domain exceptions
├── models/              # SQLAlchemy models
├── schemas/             # Pydantic schemas
├── services/            # Business logic
├── cli.py               # CLI upload tool
├── config.py            # Settings
└── main.py              # Application entrypoint
```
