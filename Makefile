.PHONY: install dev test lint format clean migrate migrate-create migrate-downgrade upload bulk-import

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

upload:
	uv run a11y-upload upload $(app_id) $(dir)

bulk-import:
	uv run a11y-upload bulk $(dir) --org-unit-id $(org_unit_id) --brand $(brand)

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .ruff_cache
