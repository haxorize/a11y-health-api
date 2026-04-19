.PHONY: install dev test lint format clean migrate migrate-create migrate-downgrade ingest import

install:
	uv sync

dev:
	uv run uvicorn a11y_health.main:app --reload

test:
	uv run pytest -v

test-cov:
	uv run pytest --cov=a11y_health --cov-report=term-missing

lint:
	uv run ruff check .
	uv run ty check src/

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

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .ruff_cache
