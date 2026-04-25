---
name: tdd
description: Test-driven development workflow using vertical slices. Use when implementing a feature, building from a spec or task, or user mentions "TDD" or "test first".
---

# Test-Driven Development

## Philosophy

Tests verify behavior through public interfaces, not implementation details. One test at a time, one implementation at a time. Never write all tests first then all code — that's horizontal slicing.

See the `testing` skill for project-specific test conventions, fixtures, and patterns.
See the `fastapi` skill for endpoint, schema, and service conventions.
See the `database` skill for ORM model, schema design, migration, and indexing conventions.

## Workflow

### 1. Plan

If a feature spec or task issue exists, pull acceptance criteria from it. If not, briefly identify:

- What interface changes are needed
- Which behaviors to test (prioritize with the user)
- Opportunities for deep modules

Confirm the plan with the user before writing any code.

### 2. Tracer bullet

Write ONE test for the first and most fundamental behavior. Run `uv run pytest` — confirm it **fails for the right reason** (behavior is missing, not a typo or import error). Write the minimal code to make it pass. Run `uv run pytest` — confirm it **passes**.

This is the tracer bullet — it proves the path works end-to-end.

### 3. Incremental loop

For each remaining behavior:

1. **RED**: Write one test for the next behavior. Run `uv run pytest` — confirm it fails for the right reason (behavior is missing, not a typo or import error).
2. **GREEN**: Write minimal code to pass. Run `uv run pytest` — confirm it passes.

Rules:

- One test at a time
- Only enough code to pass the current test
- Don't anticipate future tests
- Tests describe what the system does, not how

### 4. Refactor

After all tests pass, review the implementation before calling the task done:

- Extract duplication
- Deepen modules (move complexity behind simple interfaces)
- Simplify where the accumulated implementation reveals a cleaner design

Run `uv run pytest` after each refactor step. Never refactor while red.

Then run `/simplify` to catch any remaining issues with reuse, quality, or efficiency. Fix anything it finds and re-run `uv run pytest`.

### 5. Migration

If the task added or changed any SQLAlchemy models, generate an Alembic migration:

```bash
uv run alembic revision --autogenerate -m "add <resource> table"
```

Review the generated migration — remove false-positive detections. Test the roundtrip:

```bash
uv run alembic downgrade base && uv run alembic upgrade head
```

### 6. Lint & typecheck

After refactoring is complete and all tests pass, run formatting, linting, and type checking:

```bash
uv run ruff format .
uv run ruff check --fix .
uv run ty check
```

Fix any issues, then re-run `uv run pytest` to confirm nothing broke.

Tests and type checks verify code correctness, not feature correctness. If the change touches behavior you couldn't actually run end-to-end (e.g., a UI flow, an external integration, a real ingest), say so explicitly instead of claiming the task is done.

### 7. Update docs

Check whether the changes affect anything documented in `README.md`, `CLAUDE.md`, or `UBIQUITOUS_LANGUAGE.md` (e.g., new commands, changed structure, new conventions, new or renamed domain terms). Update if needed, skip if not.

If this slice ships as its own PR, run `/review` before pushing.
