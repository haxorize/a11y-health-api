.PHONY: install lock dev test coverage lint lint-style lint-format lint-types lint-deps format clean migrate migrate-create migrate-downgrade migrate-roundtrip openapi openapi-check

# Asserts uv.lock has not drifted from pyproject.toml, failing the command if it
# has, so editing a bound without relocking is refused instead of quietly
# resolving to something else. Set once as environment rather than as a flag per
# command: make exports it to every recipe, so a `uv` call added later inherits
# it — including one inside a script a recipe shells out to. The pre-commit hook
# and CI each export the same variable.
export UV_LOCKED := 1

# The revision `migrate-roundtrip` downgrades to. No recipe expands it:
# tests/migrations/roundtrip.py reads this line, so it cannot be overridden
# from the command line. test_downgrade_floor.py also checks that the migration
# harness is refused first at this revision on a walk from the base.
#
# b362121027a0 is the deepest revision the roundtrip can reach: its own
# downgrade() raises NotImplementedError, so it is downgraded *to* and never
# crossed. Raise this floor whenever a migration lands whose downgrade cannot
# restore its parent's schema; everything above it must stay schema-reversible,
# and test_downgrade_floor.py fails if the floor ever resolves to the head.
#
# 8b3a1162eb95 sits above the floor although its downgrade() restores none of
# the rows its upgrade() deletes: it loses rows but not schema, and the
# roundtrip runs against an empty per-run test database.
DOWNGRADE_FLOOR := b362121027a0

install:
	uv sync

# The way out of the assertion above. `uv sync` refuses to resolve a bound that
# moved, which is the point, and leaves no way to record the move — so the
# relock gets a target of its own rather than a flag a reader has to know.
# UV_LOCKED is cleared for this one recipe: inherited, it would turn the relock
# into an assertion that the lock will not change, which fails exactly when it
# is needed.
lock:
	UV_LOCKED=0 uv lock

dev:
	uv run uvicorn a11y_health.main:app --reload

test:
	uv run pytest -v

coverage:
	uv run pytest --cov=a11y_health --cov-report=term-missing

# The project's one lint set: the hook and a developer's `make lint` both run
# this target, and CI runs the subtargets separately only to keep one red step
# per tool in its UI. That enumeration in ci.yml is a second copy of the
# membership below, so a check added here has to be added there too;
# tests/test_workflow_parity.py compares them and names the side that is
# missing one. `openapi-check` is outside the comparison, being neither a
# prerequisite here nor part of the lint set.
lint: lint-style lint-format lint-types lint-deps

lint-style:
	uv run ruff check .

# Its own target rather than a second line under lint-style: make stops at the
# first failing line, so bundled, a ruff check failure meant the formatting
# failures were not reported until the check ones had been fixed and it was run
# again. CI reported both before the targets existed.
lint-format:
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

# Runs against an empty per-run test database, never DATABASE_URL. The suite
# runs the same test; this target is the one CI's migration-drift job names.
migrate-roundtrip:
	$(if $(filter command line,$(origin DOWNGRADE_FLOOR)),$(error DOWNGRADE_FLOOR is read from this Makefile by the test, so a command-line override would be ignored; edit the assignment instead))
	uv run pytest tests/migrations/test_downgrade_floor.py::test_the_revisions_above_the_floor_reverse

openapi:
	uv run python scripts/export_openapi.py

# Generates to a temp path instead of taking `openapi` as a prerequisite. As a
# prerequisite it overwrote the tracked file before reading it, so a developer
# running the check to find out whether they needed to regenerate got a clean
# report on the re-run and an unstaged regeneration sitting in their tree.
openapi-check:
	@tmp=$$(mktemp); \
	if ! uv run python scripts/export_openapi.py "$$tmp" >/dev/null; then \
		rm -f "$$tmp"; \
		echo ""; \
		echo "the OpenAPI export failed — see the traceback above; openapi.json was not read"; \
		exit 1; \
	fi; \
	if diff -q openapi.json "$$tmp" >/dev/null; then \
		rm -f "$$tmp"; \
	else \
		rm -f "$$tmp"; \
		echo ""; \
		echo "openapi.json is stale — run 'make openapi' and commit the result"; \
		exit 1; \
	fi

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .ruff_cache htmlcov cov_out
	rm -f .coverage
