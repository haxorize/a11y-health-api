.PHONY: install dev test coverage lint format clean migrate migrate-create migrate-downgrade ingest import openapi openapi-check

install:
	uv sync

dev:
	uv run uvicorn a11y_health.main:app --reload

test:
	uv run pytest -v

coverage:
	uv run pytest --cov=a11y_health --cov-report=term-missing

lint:
	uv run ruff check .
	uv run ty check
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

ingest:
	uv run a11y ingest $(dir)

import:
	uv run a11y import $(dir) --org-unit-id $(org_unit_id) --brand-id $(brand_id)

openapi:
	uv run python scripts/export_openapi.py

openapi-check: openapi
	@git diff --exit-code openapi.json || (echo "" && echo "openapi.json is stale — run 'make openapi' and commit the result" && exit 1)

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .ruff_cache htmlcov
	rm -f .coverage
