# Accessibility Health API

FastAPI + async SQLAlchemy + PostgreSQL. Python 3.13.

## Tooling

- **Package manager**: uv (not pip/poetry)
- **Linting/formatting**: ruff (not black/isort/flake8)
- **Type checking**: ty (not mypy/pyright)

## Commands

```bash
uv run pytest                    # run tests
uv run ruff check .              # lint
uv run ruff format .             # format
uv run ty check                  # type check
uv run uvicorn a11y_health.main:app --reload  # dev server
uv run a11y ingest <directory>                       # upload one scan to an existing app
uv run a11y import <directory> --org-unit-id <id> --brand-id <id>  # onboard an app with history
```

## Structure

Source in `src/a11y_health/`. Tests in `tests/`. Config in `pyproject.toml`.
Endpoints in `api/v1/endpoints/`, models in `models/`, schemas in `schemas/`, services in `services/`.

## Domain Language

See `UBIQUITOUS_LANGUAGE.md` for canonical domain terms. Use those terms in code, comments, and conversation.

## Architecture Decisions

See `docs/adr/` for recorded architectural decisions and their rationale. Consult before making choices that touch the same areas; respect existing decisions unless the user explicitly wants to revisit one.
