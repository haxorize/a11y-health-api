# Test runner recipes

Coverage and runner-flag commands for the test suite. Pulled out of `SKILL.md` to keep the main file focused on writing tests.

## Coverage

`pytest-cov` is wired up. Common invocations:

```bash
uv run pytest --cov=a11y_health --cov-report=term-missing       # uncovered line numbers inline
uv run pytest --cov=a11y_health --cov-report=html               # browse htmlcov/index.html
uv run pytest --cov=a11y_health --cov-report=annotate:cov_out   # per-file annotated source ('!' = uncovered)
```

Chase coverage by module: `--cov=a11y_health.services.score_snapshot`.

## Running tests

```bash
uv run pytest -x                     # stop on first failure
uv run pytest --lf                   # rerun only last-failed
uv run pytest --ff                   # last-failed first, then the rest
uv run pytest --pdb                  # drop into debugger on failure
uv run pytest -k "scan and not run"  # filter by name expression
uv run pytest -m "not slow"          # skip slow tests
```
