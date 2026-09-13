---
title: "Yield-dependency teardown commit races the client's next request"
problem_type: integration_issue
tags: [fastapi, sqlalchemy, transaction, dependency-scope, flake, e2e]
symptoms:
  - "404 not_found for a resource a 201 just returned"
  - "seed: list seed pages for run 2 failed — 404 Scan run 2 not found"
  - "e2e seed flakes in CI but passes locally and on re-run"
  - "POST 201 then immediate GET 404 on the same resource"
root_cause: "FastAPI's default request scope runs get_db()'s commit after the response is sent, so a sequential client's next request can beat the commit"
module: api/deps
date: 2026-07-15
---

# Yield-dependency teardown commit races the client's next request

## Problem

The a11y-health-ui e2e seed flaked in CI: `POST /apps/1/scan-runs` returned 201 with the new run's id, and the immediately-following `GET /scan-runs/2/pages` returned 404 for that same run. Same uvicorn process, same Postgres, sequential requests on one keep-alive connection.

## What didn't work

- Suspecting the seed's reconciliation logic or test parallelism — seeding runs once in Playwright `globalSetup`, and the api.log artifact showed the requests arriving strictly in order.
- Reproducing locally with 200 plain POST→GET cycles — zero failures. On a fast machine the teardown commit always wins the race; only a loaded CI runner (or an artificial commit delay) loses it, which is why the flake passed on PR and failed on the main push of the identical commit.

## Fix

`get_db()` commits in its yield-dependency teardown, and FastAPI's default `Depends(..., scope="request")` runs that teardown **after** the response is sent. Declare the session dependency with function scope so the commit is ordered before the client can act on the response:

```python
# api/deps.py
DbSession = Annotated[AsyncSession, Depends(get_db, scope="function")]
```

`scope="function"` (FastAPI ≥ 0.121) runs teardown after the endpoint returns but before the response is sent. Proven by patching a 50 ms delay into `AsyncSession.commit` and hammering 200 sequential POST-scan-run → GET-pages cycles: request scope failed 200/200, function scope 0/200.

## Prevention

- The scope choice is recorded at the `Depends` site in `api/deps.py`, and `docs/architecture.md` ("How the database session and transactions work") points here for the rationale — any new session-like yield dependency should copy the function scope.
- Watch for this on FastAPI upgrades: teardown timing has already flipped once upstream (0.118 moved it after the response; 0.121 added the opt-out).
