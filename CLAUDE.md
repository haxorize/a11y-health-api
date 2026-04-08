# Accessibility Health API

FastAPI + async SQLAlchemy + PostgreSQL. Python 3.14.

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
```

## Structure

Source in `src/a11y_health/`. Tests in `tests/`. Config in `pyproject.toml`.
Endpoints in `api/v1/endpoints/`, models in `models/`, schemas in `schemas/`, services in `services/`.
