# Accessibility Quality API

A REST API for accessibility quality analysis, built with FastAPI, async SQLAlchemy, and Pydantic.

## Requirements

- Python 3.14+
- [uv](https://docs.astral.sh/uv/) package manager

## Setup

```sh
# Install dependencies
make install

# Enable pre-commit hooks
git config core.hooksPath .githooks

# Run the development server
make dev
```

The API will be available at `http://localhost:8000` with interactive docs at `http://localhost:8000/api/v1/openapi.json`.

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
| `DATABASE_URL` | `sqlite+aiosqlite:///./a11y_quality.db` | Database connection string |
| `ALLOWED_ORIGINS` | `["http://localhost:3000"]` | CORS allowed origins |

## Project Structure

```
src/a11y_quality_api/
├── api/
│   ├── deps.py          # Dependency injection
│   └── v1/
│       ├── endpoints/   # Route handlers
│       └── router.py    # API router
├── core/
│   └── database.py      # Database setup
├── models/              # SQLAlchemy models
├── schemas/             # Pydantic schemas
├── services/            # Business logic
├── config.py            # Settings
└── main.py              # Application entrypoint
```
