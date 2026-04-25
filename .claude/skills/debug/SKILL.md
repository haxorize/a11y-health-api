---
name: debug
description: Systematic debugging workflow for this project. Use when investigating a bug, a failing test, or unexpected behavior.
---

# Debug

Approach bugs systematically: reproduce → hypothesize → test → fix the root cause. Skipping to a guess that "happens to make the test pass" usually masks the bug rather than fixing it.

## Workflow

### 1. Reproduce reliably

Get the failure to happen on demand. Until you can trigger it consistently, you're guessing.

- For a failing test: run just that test with `uv run pytest tests/path/test_x.py::test_name -x -v`. If it's flaky, run it ~10x in a loop to confirm the failure rate.
- For an endpoint or CLI failure: capture the exact request, payload, or command that triggers it.
- For a regression: `git bisect` to find the commit that introduced the bug.

### 2. Form a hypothesis

State what you think is happening, specifically:

- Which function or layer is the likely source?
- What state would have to be true for the bug to occur?
- Which observation would confirm or refute this?

Vague hypotheses ("something's wrong with the session") aren't testable. Sharpen until concrete.

### 3. Test the hypothesis

Cheap probes before clever fixes. Add a print, drop into `pdb`, or write a focused test that confirms or refutes the hypothesis.

If the probe refutes the hypothesis, return to step 2 with what you learned. Don't proceed to step 4 on a hypothesis you haven't verified.

### 4. Fix the root cause

Once the hypothesis is confirmed, fix the underlying cause — not the symptom.

- If the bug is in a service, fix the service. Don't patch around it in the endpoint.
- If a test is wrong, fix the test. Don't loosen assertions to make it pass.
- Write a test that reproduces the bug **before** the fix — it proves the fix works and prevents regression.
- When describing the fix (in chat, commits, PR bodies), describe the **behavior and contract**, not file paths and line numbers. "Best-practice violations should affect the score the same as WCAG violations" stays valid through refactors; "fix `services/score.py:142`" doesn't.

## Common project pitfalls

- **AsyncSession isn't concurrent-safe.** Tests using `db_client` share one session — parallel HTTP calls inside a single test will deadlock or corrupt state. Same applies to production code: don't `asyncio.gather` operations on a shared session.
- **Transactional rollback boundary.** `db_session` runs inside a rolled-back transaction. If a service or test calls `commit()`, state leaks across tests and isolation breaks.
- **Migration roundtrip.** Alembic autogenerate often misses index/constraint changes. Verify with `uv run alembic downgrade base && uv run alembic upgrade head`.
- **Use `pytest -x`.** Stop at the first failure to keep the diagnostic signal clean — chained failures from a single root cause are noise.

## When stuck

If two rounds of the loop don't converge:

- Step back. Are you debugging the right thing? The reported symptom may be downstream of a different bug.
- Re-read the relevant code from scratch. Assumptions about how the code works are often wrong.
- Ask the user. Describe what you've tried and what you've ruled out.
