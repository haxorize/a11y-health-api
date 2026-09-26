# a11y-health-api

FastAPI + async SQLAlchemy + PostgreSQL. Python 3.14.

## Tooling

- **Package manager**: uv (not pip/poetry)
- **Linting/formatting**: ruff (not black/isort/flake8)
- **Type checking**: ty (not mypy/pyright)
- **Testing**: pytest

## Prerequisites

Postgres running at `localhost:5432/a11y_health`. See `.env.example` for the 4 settings an operator sets, which are all of `Settings`; `PROJECT_NAME`, `VERSION` and `API_V1_PREFIX` are module constants in `src/a11y_health/config.py`, because each reaches the committed `openapi.json`.

Postgres **15** specifically (`brew install postgresql@15`) — CI's service container and the sibling UI's e2e job both run `postgres:15`, and a bare `brew install postgresql` installs 18 today, which diverges from what the suite is measured against. ADR 0013 owns the PostgreSQL dependency but records no version, so this line is where the major lives. The floor is 14, because `get_ancestors` in `services/org_unit.py` uses a recursive CTE's `CYCLE` clause, which PostgreSQL added in 14.

`make` on PATH — the hook runs `make lint`, `make openapi-check` and `make test`, so a machine without it (a slim container, macOS without the Xcode command line tools) fails the hook after the worktree is built. Apple's GNU Make 3.81 is enough; there is no version floor.

`gitleaks` on PATH (`brew install gitleaks`) — the first stage of `.githooks/pre-commit`, which scans the staged changes before any other check runs. That is not a guarantee a secret cannot reach history: the hook runs only once `core.hooksPath` is wired per clone (§ Commands), and `git commit --no-verify` skips it. The backstop is `ci.yml`'s lint job, which scans the whole history (`fetch-depth: 0`) on every push to `main` and every pull request against it.

## Commands

```bash
uv run pytest                    # run tests
uv run ruff check .              # lint
uv run ruff format .             # format
uv run ty check                  # type check
uv run deptry src migrations scripts  # unused / missing / transitive dependencies (same paths as the hook and CI)
make lock                        # re-resolve uv.lock after editing a dependency bound (make, the hook, the scripts and CI export UV_LOCKED, so their uv calls assert it has not drifted; a bare `uv run` above does not)
uv run uvicorn a11y_health.main:app --reload  # dev server
uv run a11y --help               # onboarding CLI: import/ingest + org-unit/brand lookups (see cli/__init__.py docstring)
gh run view --log-failed         # a red CI run's failing step output, without opening the browser
```

Run: `make dev` (:8000) — up when `curl -s localhost:8000/api/v1/health` returns `{"status":"healthy"}` (Postgres from § Prerequisites has to answer `pg_isready` first). `make migrate` seeds the state — root org unit 1 `Humana Inc.` and brands 1–5 (`Humana`, `CenterWell`, `Go365`, `CarePlus`, `Reliance`). The brands are API-read-only: there is no `POST`, `PATCH` or `DELETE /brands`. The root org unit is **not** — `POST`, `PATCH` and `DELETE /org-units` are all live, nothing special-cases id 1, and a freshly seeded root has no dependents, so `DELETE /api/v1/org-units/1` deletes it and returns 204. For a scratch database instead, the recipe is the `verify` skill.

Wire two things per clone, because neither travels in the repo: `git config core.hooksPath .githooks` for the checks below, and `git config blame.ignoreRevsFile .git-blame-ignore-revs` so `git blame` looks through the whitespace-only reflow that touched a third of the docs tree. Without the second, every line under `docs/` the reflow touched and no later commit has rewritten blames to that commit instead of to whatever last changed its words. No count is given here, because each docs edit shrinks it.

`.githooks/pre-commit` (wired via `core.hooksPath`) is the list of per-commit checks — read the file rather than a summary of it. It ends with the full suite, and two consequences are worth planning around: a commit costs the suite plus a secret scan, a checkout of the index, a dependency sync into it, the full lint stage (`ruff check`, `ruff format --check`, `ty`, `deptry`), and a second full import of the application for the OpenAPI stage — measurably more than `make test` alone, so budget against the hook and not against the suite — and **every commit in a multi-commit split has to pass on its own**, so a split that leaves an intermediate commit broken can't be made. The hook enforces that second one rather than assuming it, by running the checks against a checkout of the index; ADR 0046 records the design and what it replaced.

Two CI checks stay out of the hook, both Alembic stages in the `migration-drift` job: `Migration roundtrip` and `Check for model/migration drift`. Each needs a live Postgres to upgrade and downgrade against, and a hook that reached for a developer's database would either rewrite it or fail on a machine that has none — which is also why the OpenAPI staleness check *is* in the hook, being the one CI stage of the three that needs no database. The roundtrip's downgrade floor is `DOWNGRADE_FLOOR` in the `Makefile`, where the person adding a migration can see it; CI gets it by invoking `make migrate-roundtrip` rather than keeping a copy. The target builds its own scratch database rather than using `DATABASE_URL`, so the stage is safe to run anywhere and the floor can sit below the head, where it downgrades across something; `tests/migrations/test_downgrade_floor.py` fails if it ever reaches the head again.

## Structure

Source in `src/a11y_health/`. Tests in `tests/`. Config in `pyproject.toml`. Endpoints in `api/v1/endpoints/`, models in `models/`, schemas in `schemas/`, services in `services/`, the deep modules in `core/`, the onboarding CLI in `cli/`, and Alembic revisions in `migrations/` at the repo root.

## Subagent delegation

Subagent delegation is authorized — standing permission, not a per-session ask. A skill specifying subagent fan-out or a fresh-context pass uses it rather than substituting an inline pass: a cold reader sharing the author's context isn't a cold reader, and review lenses that run inline stop being independent.

## Convention skills

Project-local skills that carry this repo's conventions — one per layer, plus the cross-repo `contract-change` procedure. The global `tdd`, `implement`, and `feedback-loops` skills discover and invoke the layer skills *by role* for whatever layer a slice touches — consult the matching one before writing code at that layer, and `feedback-loops` applies any stack finalization they own (e.g. migrations).

- **`database`** — data layer: PostgreSQL schema design, SQLAlchemy models/columns/types, migrations, indexes/constraints, and query patterns. Owns migration finalization after a model change.
- **`fastapi`** — backend layer: endpoints, schemas, services, and app configuration.
- **`testing`** — test layer: fixtures, factories, test layout, markers, and mocking.
- **`code-documentation`** — prose layer: where an explanation lives, when a docstring is written, the 80-column wrap `W505` checks over code prose, the short-line shape `test_prose_shape.py` checks, the one-line-per-paragraph rule it checks over markdown (ADR 0040), the American spelling it checks over both (ADR 0041), the 100-word ceiling it checks over a `DOMAIN.md` definition (ADR 0018), the word band and em-dash cap it checks over `docs/architecture.md` (#148), the 15,000-byte re-attach bound it checks over every skill body and reference, and the fix a failure from each asks for.
- **`contract-change`** — the two-repo OpenAPI procedure; a copy of the workspace root's skill, hash-locked in `skills-sync.lock` — edit it at the root and run `scripts/sync-skills.sh` there, never here.
- **`verify`** — the build/launch/drive recipe for checking a change against a live dev server, including the scratch-database setup § Commands points at.

## Domain language

See `DOMAIN.md` for canonical domain terms. Use those terms in code, comments, and conversation.

## Architecture decisions

See `docs/adr/` for recorded architectural decisions and their rationale. Consult before making choices that touch the same areas; respect existing decisions unless the user explicitly wants to revisit one.

## Solved problems

`docs/solutions/` — solved problems keyed by symptom frontmatter (one Learning doc per diagnosis).

## Code documentation

Comprehension lives in prose, not blanket docstrings (ADR 0018): `docs/architecture.md` carries the behavioral and structural story and `docs/operating.md` the operating one, split by 0018's 2026-09-13 amendment. The rules and the guards that check them are the `code-documentation` skill. `tests/test_prose_shape.py` holds six of those rules — the short-line shape over code prose, one line per paragraph over markdown (ADR 0040), the American spelling over both (ADR 0041), the 100-word ceiling on a `DOMAIN.md` definition (ADR 0018), the word band and em-dash cap on `docs/architecture.md` (#148's criterion, recorded in ADR 0018's 2026-09-19 amendment), and the 15,000-byte re-attach bound on every skill body and reference (the skills repo's figure, which no ADR or criterion carries) — each with a floor or a guard holding its own walk honest.

## Review lenses

`review-changes` runs one declared lens here on top of its standing set: a **docstring-regime lens** over any diff that touches a docstring, a comment block, or a markdown document, reporting each new or edited block against ADR 0018 — a docstring only where the signature cannot carry the contract, no `Args:`/`Returns:` blocks, no restated types. `W505` and `tests/test_prose_shape.py` fail a prose *shape*; neither asks whether the prose was owed at all, which is what this lens reads.

No other lens is declared, and the three absences are deliberate. No accessibility lens: this repo stores and scores accessibility findings, and serves JSON plus the framework's generated docs pages while authoring no interface of its own, so that surface is `../a11y-health-ui`'s. No guard lens: the suite's own invariant tests (`test_import_honesty.py`, `test_sibling_imports.py`, `test_declaration_honesty.py`, `test_reachability.py` and `test_shared_skill_lock.py` among them) hold those lines, and a review lens would only restate them. No vocabulary lens: DOMAIN conformance already runs as one of `review-changes`' standing lenses.

## Registry

- Unattested publishers: accept

## Issue tracker

- Tracker: GitHub
- Visibility: private
- Hierarchy: optional

Work items are created only through the `to-*` publishers (`/to-feature`, `/to-story`, `/to-tasks`, `/to-bug`) — never drafted and pushed with raw `gh`/`az` calls. On a casual ask ('file a story'), name the right publisher and stop.

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

## Hooks wired from outside this repo

Two tracked artifacts here are read by global agent hooks, not by anything in this checkout. Both are wired by absolute path from `~/.claude/settings.json` into `~/code/src/humana/skills/global/hooks/`, so **a second clone, another machine, or CI has the artifact and no hook** — neither is enforced by `.githooks/pre-commit` or `ci.yml`, and `main` is unprotected.

- `.claude/rename-safety` — an empty opt-in **marker**, not a config file. It turns on `rename-safety.sh`, which blocks `sed -i`, `perl -i`, `ruby -i` and `xargs` feeding them in any directory under it. The file must stay empty: the hook tests `-f` and never reads the contents. Deleting it to unblock an edit disarms the guard repo-wide.
- `Review required: yes` under § Landing — read by `review-receipt.sh`, which refuses a `git push` unless a report in the temp-dir landing zone carries a `Reviewed-tree:` stamp matching the tree being pushed. A push the user runs in their own terminal is its one skip path.

Both hooks fail **open**, and on more than a missing marker: without `python3` on PATH they allow every command, announce one line on stderr, and exit 0 — so `rename-safety` stops blocking `sed -i` and `Review required: yes` stops gating pushes, with nothing in this repo checking for the condition or going red on it. `python3` is in `README.md` § Requirements for that reason; uv manages the project interpreter without putting one on PATH.

The other Landing keys are read by skills only. `Push pre-authorized:` and `Ticket close pre-authorized:` have no hook behind them and gate nothing mechanically.

## Sibling repos

- `../a11y-health-ui`: consumes this repo's REST contract through the generated client; a contract change lands in both repos together (`contract-change`).
