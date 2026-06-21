# a11y-health-api

FastAPI + async SQLAlchemy + PostgreSQL. Python 3.13.

## Tooling

- **Package manager**: uv (not pip/poetry)
- **Linting/formatting**: ruff (not black/isort/flake8)
- **Type checking**: ty (not mypy/pyright)
- **Testing**: pytest

## Prerequisites

Postgres running at `localhost:5432/a11y_health`. See `.env.example` for the full env config.

## Commands

```bash
uv run pytest                    # run tests
uv run ruff check .              # lint
uv run ruff format .             # format
uv run ty check                  # type check
uv run uvicorn a11y_health.main:app --reload  # dev server
uv run a11y --help               # data import/ingest commands (see cli.py module docstring)
```

## Structure

Source in `src/a11y_health/`. Tests in `tests/`. Config in `pyproject.toml`.
Endpoints in `api/v1/endpoints/`, models in `models/`, schemas in `schemas/`, services in `services/`.

## Convention skills

Project-local skills that carry this repo's conventions, organized by the layer they own. The global `tdd`, `implement`, and `feedback-loops` skills discover and invoke these *by role* for whatever layer a slice touches — consult the matching one before writing code at that layer, and `feedback-loops` applies any stack finalization they own (e.g. migrations).

- **`database`** — data layer: PostgreSQL schema design, SQLAlchemy models/columns/types, migrations, indexes/constraints, and query patterns. Owns migration finalization after a model change.
- **`fastapi`** — backend layer: endpoints, schemas, services, and app configuration.
- **`testing`** — test layer: fixtures, factories, test layout, markers, and mocking.

## Domain Language

See `DOMAIN.md` for canonical domain terms. Use those terms in code, comments, and conversation.

## Architecture Decisions

See `docs/adr/` for recorded architectural decisions and their rationale. Consult before making choices that touch the same areas; respect existing decisions unless the user explicitly wants to revisit one.

## Issue tracker

- Tracker: GitHub
- Hierarchy: optional
