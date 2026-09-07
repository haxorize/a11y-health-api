# a11y-health-api

FastAPI + async SQLAlchemy + PostgreSQL. Python 3.14.

## Tooling

- **Package manager**: uv (not pip/poetry)
- **Linting/formatting**: ruff (not black/isort/flake8)
- **Type checking**: ty (not mypy/pyright)
- **Testing**: pytest

## Prerequisites

Postgres running at `localhost:5432/a11y_health`. See `.env.example` for the full env config.

`gitleaks` on PATH (`brew install gitleaks`) — the pre-commit hook's first stage; a commit cannot be made without it.

## Commands

```bash
uv run pytest                    # run tests
uv run ruff check .              # lint
uv run ruff format .             # format
uv run ty check                  # type check
uv run deptry src migrations scripts  # unused / missing / transitive dependencies (same paths as the hook and CI)
uv run uvicorn a11y_health.main:app --reload  # dev server
uv run a11y --help               # onboarding CLI: import/ingest + org-unit/brand lookups (see cli/__init__.py docstring)
gh run view --log-failed         # a red CI run's failing step output, without opening the browser
```

Run: `make dev` (:8000) — up when `curl -s localhost:8000/api/v1/health` returns
`{"status":"healthy"}`; needs only Postgres at `localhost:5432/a11y_health`
(`pg_isready`) up first. `make migrate` seeds the state — root org unit 1 `Humana Inc.`
and brands 1–5 (`Humana`, `CenterWell`, `Go365`, `CarePlus`, `Reliance`), all
API-read-only. For a scratch database instead, the recipe is the `verify` skill.

`.githooks/pre-commit` (wired via `core.hooksPath`) is the list of per-commit checks —
read the file rather than a summary of it. It ends with the full suite, and two consequences
are worth planning around: a commit takes as long as the suite does, and **every commit in a
multi-commit split has to pass on its own**, so a split that leaves an intermediate
commit broken can't be made.

## Structure

Source in `src/a11y_health/`. Tests in `tests/`. Config in `pyproject.toml`.
Endpoints in `api/v1/endpoints/`, models in `models/`, schemas in `schemas/`, services in `services/`.

## Subagent delegation

Subagent delegation is authorized — standing permission, not a per-session ask. A skill specifying subagent fan-out or a fresh-context pass uses it rather than substituting an inline pass: a cold reader sharing the author's context isn't a cold reader, and review lenses that run inline stop being independent.

## Convention skills

Project-local skills that carry this repo's conventions — one per layer, plus the cross-repo `contract-change` procedure. The global `tdd`, `implement`, and `feedback-loops` skills discover and invoke the layer skills *by role* for whatever layer a slice touches — consult the matching one before writing code at that layer, and `feedback-loops` applies any stack finalization they own (e.g. migrations).

- **`database`** — data layer: PostgreSQL schema design, SQLAlchemy models/columns/types, migrations, indexes/constraints, and query patterns. Owns migration finalization after a model change.
- **`fastapi`** — backend layer: endpoints, schemas, services, and app configuration.
- **`testing`** — test layer: fixtures, factories, test layout, markers, and mocking.
- **`code-documentation`** — prose layer: where an explanation lives, when a docstring is written, the 80-column wrap `W505` checks and the short-line shape `test_prose_shape.py` checks, and the rewrap rule a failure from either asks for.
- **`contract-change`** — the two-repo OpenAPI procedure; a copy of the workspace root's skill, hash-locked in `skills-sync.lock` — edit it at the root and run `scripts/sync-skills.sh` there, never here.

## Domain language

See `DOMAIN.md` for canonical domain terms. Use those terms in code, comments, and conversation.

## Architecture decisions

See `docs/adr/` for recorded architectural decisions and their rationale. Consult before making choices that touch the same areas; respect existing decisions unless the user explicitly wants to revisit one.

## Solved problems

`docs/solutions/` — solved problems keyed by symptom frontmatter (one Learning doc per diagnosis).

## Code documentation

Comprehension lives in prose, not blanket docstrings (ADR 0018); the rules and the two guards that check them are the `code-documentation` skill.

## Registry

- Unattested publishers: accept

## Issue tracker

- Tracker: GitHub
- Visibility: private
- Hierarchy: optional

Work items are created only through the `to-*` publishers (`/to-feature`, `/to-story`,
`/to-tasks`, `/to-bug`) — never drafted and pushed with raw `gh`/`az` calls. On a casual
ask ('file a story'), name the right publisher and stop.

## Bug severity labels

- critical → `sev:critical` — outage, data loss, security
- high → `sev:high` — broken core flow, no workaround
- medium → `sev:medium` — non-core flow, or core flow with workaround
- low → `sev:low` — cosmetic, edge-case

## Landing

- Branch policy: trunk
- PR required: no
- Push pre-authorized: no
- Ticket close pre-authorized: no
- Review required: yes
- Defect policy: fix, don't file

## Sibling repos

- `../a11y-health-ui`: consumes this repo's REST contract through the generated client; a contract change lands in both repos together (`contract-change`).
