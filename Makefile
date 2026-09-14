.PHONY: install dev test coverage lint lint-style lint-types lint-deps format clean migrate migrate-create migrate-downgrade migrate-roundtrip openapi openapi-check

# Asserts uv.lock has not drifted from pyproject.toml, failing the command if it
# has, so editing a bound without relocking is refused instead of quietly
# resolving to something else. Set once as environment rather than as a flag per
# command: make exports it to every recipe, so a `uv` call added later inherits
# it — including one inside a script a recipe shells out to. The pre-commit hook
# and CI each export the same variable.
export UV_LOCKED := 1

# The revision `migrate-roundtrip` downgrades to, and the floor CI's
# migration-drift job gets by invoking that target rather than carrying a copy.
#
# It is the current head. 8b3a1162eb95's upgrade() re-runs the #97 dedupe
# DELETE over score_snapshot, and its downgrade() restores none of the rows that
# DELETE removes — it only puts the dropped uniqueness indexes back. So going
# below it and coming back up re-runs that DELETE against a window where the
# indexes were absent, and removes whatever duplicate rollup snapshots landed in
# it without a word. Raise this floor whenever a migration lands whose downgrade
# cannot undo its upgrade; everything above it must stay reversible. While the
# floor is the head the roundtrip exercises no revisions, and that coverage
# comes back with the next reversible migration.
DOWNGRADE_FLOOR := 8b3a1162eb95

install:
	uv sync

dev:
	uv run uvicorn a11y_health.main:app --reload

test:
	uv run pytest -v

coverage:
	uv run pytest --cov=a11y_health --cov-report=term-missing

# The project's one lint set, so the hook and CI cannot drift from each other or
# from a developer's `make lint`: the hook runs this target, and CI runs the
# three subtargets separately only to keep one red step per tool in its UI.
lint: lint-style lint-types lint-deps

lint-style:
	uv run ruff check .
	uv run ruff format --check .

lint-types:
	uv run ty check

lint-deps:
	uv run deptry src migrations scripts

format:
	uv run ruff format .
	uv run ruff check --fix .

migrate:
	uv run alembic upgrade head

migrate-create:
	uv run alembic revision --autogenerate -m "$(msg)"

migrate-downgrade:
	uv run alembic downgrade -1

migrate-roundtrip:
	uv run alembic upgrade head
	uv run alembic downgrade $(DOWNGRADE_FLOOR)
	uv run alembic upgrade head

openapi:
	uv run python scripts/export_openapi.py

openapi-check: openapi
	@git diff --exit-code openapi.json || (echo "" && echo "openapi.json is stale — run 'make openapi' and commit the result" && exit 1)

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .ruff_cache htmlcov
	rm -f .coverage
