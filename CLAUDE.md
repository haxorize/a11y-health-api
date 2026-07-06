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

## Solved problems

`docs/solutions/` — solved problems keyed by symptom frontmatter (one Learning doc per diagnosis).

## Code documentation

Comprehension lives in prose, not blanket docstrings — see [ADR 0018](docs/adr/0018-documentation-strategy-prose-over-docstrings.md) for the why. The rules:

- **Explain the non-obvious; never restate what types and names already say.** No `Args:`/`Returns:` blocks (the type hints carry that), no docstring on a module whose purpose is clear from its path. Docstrings, when written, are plain prose.
- **Cross-cutting behavior and architecture go in [`docs/architecture.md`](docs/architecture.md)** (the layer model, scoring/rollup, scan-run lifecycle, pagination, contract pipeline, operating). `DOMAIN.md` stays a glossary.
- **Module docstrings only on modules whose job isn't self-evident** (e.g. scoring, pagination, the axe boundary), and they point to the relevant `architecture.md` section rather than re-explaining it.
- **Function docstrings only for a caller contract the signature can't express** — a precondition or a `Raises:` (see `paginate()`).

No ruff `D` rules enforce this; it's judgment, applied here.

## Issue tracker

- Tracker: GitHub
- Hierarchy: optional
