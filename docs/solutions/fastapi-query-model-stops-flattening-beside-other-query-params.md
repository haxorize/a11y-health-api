---
title: "FastAPI Query() parameter model stops flattening beside other query params"
problem_type: integration_issue
tags: [fastapi, pydantic, query-params, parameter-model, depends, pagination]
symptoms:
  - '422 {"loc": ["query", "pagination"], "msg": "Field required"}'
  - "every request to the endpoint returns 422 Unprocessable Entity after converting query params to a Pydantic model"
  - "query parameter model treated as one required query parameter named after the function argument instead of flattening into its fields"
root_cause: "A Query() parameter model silently stops flattening into its fields when the endpoint declares any other query parameter — a FastAPI design limitation, not a regression"
module: core/pagination
date: 2026-07-06
---

# FastAPI Query() parameter model stops flattening beside other query params

## Problem

Converting `cursor`/`limit` into a Pydantic query-parameter model — `Annotated[PaginationParams, Query()]`, FastAPI's documented form since 0.115 — made every request to `list_apps`/`list_findings` return `422 {"loc": ["query", "pagination"], "msg": "Field required"}`. FastAPI stopped flattening the model into `cursor`/`limit` and instead expected a single query parameter named after the argument.

## What didn't work

- **The documented `Query()` parameter-model form.** It works only while the endpoint declares *no other query parameter*. The moment a sibling query param exists (plain scalar or `Annotated[..., Query()]`), flattening silently turns off. Path parameters and `Depends()` siblings co-exist fine — which is why endpoints without extra query filters passed and only `list_apps`/`list_findings` (which have filter params) failed.
- **Treating it as a version regression.** A minimal repro swept FastAPI 0.115.13 → 0.139.0: red on every version. Never supported; upgrading or pinning cannot fix it. The sweep was not re-run at the pinned 0.141.1, so that version is unmeasured rather than known-red.

## Fix

Declare the same Pydantic model as a dependency instead: `Annotated[PaginationParams, Depends()]` (the `PageParams` alias in `core/pagination.py`). A model dependency flattens into identical flat query parameters, produces the same OpenAPI schemas, keeps model-level validation (`ge=1`/`le=100` bounds, default), and composes with any other query parameters on the endpoint.

## Prevention

- Why-comment on `PageParams` in `src/a11y_health/core/pagination.py` records the Depends-not-Query rationale at the point of temptation.
- `test_openapi_page_size_bounds_and_default_propagate_from_the_module` (`tests/core/test_pagination.py`) sweeps every operation serving the `Page` envelope — including ones with sibling query filters — and asserts `limit` still surfaces as a flat query param with the module's bounds/default, so a revert to `Query()` fails the suite instead of shipping 422s.
