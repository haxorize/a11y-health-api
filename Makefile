.PHONY: install dev test lint format clean

install:
	uv sync

dev:
	uv run uvicorn a11y_quality_api.main:app --reload

test:
	uv run pytest -v

test-cov:
	uv run pytest --cov=a11y_quality_api --cov-report=term-missing

lint:
	uv run ruff check .
	uv run ty check src/

format:
	uv run ruff format .
	uv run ruff check --fix .

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache .ruff_cache
