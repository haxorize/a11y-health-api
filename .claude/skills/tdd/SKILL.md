---
name: tdd
description: Test-driven development workflow using vertical slices. Use when implementing a feature, building from a spec or task, or user mentions "TDD" or "test first".
---

# Test-Driven Development

## Philosophy

Tests verify behavior through public interfaces, not implementation details. One test at a time, one implementation at a time. Never write all tests first then all code — that's horizontal slicing.

See the `testing` skill for project-specific test conventions, fixtures, and patterns.

## Workflow

### 1. Plan

If a feature spec or task issue exists, pull acceptance criteria from it. If not, briefly identify:

- What interface changes are needed
- Which behaviors to test (prioritize with the user)
- Opportunities for deep modules

Confirm the plan with the user before writing any code.

### 2. Tracer bullet

Write ONE test for the first and most fundamental behavior. Run `uv run pytest` — confirm it **fails**. Write the minimal code to make it pass. Run `uv run pytest` — confirm it **passes**.

This is the tracer bullet — it proves the path works end-to-end.

### 3. Incremental loop

For each remaining behavior:

1. **RED**: Write one test for the next behavior. Run `uv run pytest` — confirm it fails.
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
