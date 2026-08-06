# a11y-health-api

FastAPI + async SQLAlchemy + PostgreSQL. Python 3.14.

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
uv run a11y --help               # onboarding CLI: import/ingest + org-unit/brand lookups (see cli/__init__.py docstring)
```

`.githooks/pre-commit` (wired via `core.hooksPath`) runs all four checks on every
commit — format, lint, `ty check src/`, and the full suite. Two consequences worth
planning around: a commit takes as long as the suite does, and **every commit in a
multi-commit split has to pass on its own**, so a split that leaves an intermediate
commit broken can't be made.

## Structure

Source in `src/a11y_health/`. Tests in `tests/`. Config in `pyproject.toml`.
Endpoints in `api/v1/endpoints/`, models in `models/`, schemas in `schemas/`, services in `services/`.

## Convention skills

Project-local skills that carry this repo's conventions, organized by the layer they own. The global `tdd`, `implement`, and `feedback-loops` skills discover and invoke these *by role* for whatever layer a slice touches — consult the matching one before writing code at that layer, and `feedback-loops` applies any stack finalization they own (e.g. migrations).

- **`database`** — data layer: PostgreSQL schema design, SQLAlchemy models/columns/types, migrations, indexes/constraints, and query patterns. Owns migration finalization after a model change.
- **`fastapi`** — backend layer: endpoints, schemas, services, and app configuration.
- **`testing`** — test layer: fixtures, factories, test layout, markers, and mocking.

## Domain language

See `DOMAIN.md` for canonical domain terms. Use those terms in code, comments, and conversation.

## Architecture decisions

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

## Commit style

Subjects **narrate what the code does**, in declarative present tense — "The
score reads move into the dispatcher, and three listers become one", not "Move
score reads" or "refactor: score reads". The subject describes the change's
effect on the codebase, never the author's action. No conventional-commit
prefixes, sentence case, no trailing period.

- **Two clauses joined by "and" or ";"** when the change has two halves; one
  clause when it doesn't. Don't manufacture a second clause.
- **Ticket refs in parentheses at the end** — `(#129)`, or `(#128,
  a11y-health-ui#57)` for cross-repo. `Closes #N` goes in the body, where it
  closes the issue on push to `main`.
- **Bodies are prose paragraphs, not bullet lists**, and carry a labeled section
  where one earns its place: `Deliberately not applied:`, `Doc drift the story
  created, closed:`.
- **A decision record commits before the code it shapes** — see the lineage rule
  the `ship` skill applies.

The sibling UI repo does *not* share this convention (it mixes imperative and
declarative, and refs differ), which is why this lives here rather than in the
workspace `CLAUDE.md`.

## Issue tracker

- Tracker: GitHub
- Hierarchy: optional

## Bug severity labels

- critical → `sev:critical` — outage, data loss, security
- high → `sev:high` — broken core flow, no workaround
- medium → `sev:medium` — non-core flow, or core flow with workaround
- low → `sev:low` — cosmetic, edge-case
