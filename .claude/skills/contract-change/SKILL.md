---
name: contract-change
description: The two-repo procedure for changing the Accessibility Health REST contract — endpoint, schema, or response shape — so the API's OpenAPI spec and the UI's generated client land together. Use when adding or modifying an endpoint, schema, response shape, or operation id in the API, when the UI needs a field or operation the generated client lacks, or when `openapi.json` or `src/client/` shows up in a diff.
---

# Contract change

The API is the source of truth and the contract is `a11y-health-api/openapi.json`; the UI consumes it through `@hey-api/openapi-ts` into `a11y-health-ui/src/client/` (types, fetch SDK, Zod response validators, TanStack Query options). Both artifacts are committed so a PR diff shows the contract moving. A change to one side without the other is the drift this procedure exists to prevent: `tsc` catches a type break at build time, and a Zod `ZodError` at the call site catches a shape the types did not, but only after the client is regenerated.

## Workflow

1. **API first.** Make the change, then `make openapi` regenerates `openapi.json` deterministically. Operation ids drive the UI's method names — `_operation_id` in `src/a11y_health/main.py` — so a renamed operation is a UI rename too. Commit `openapi.json` in the same change as the code; `make openapi-check` is the drift check, and CI runs the same two commands (`scripts/export_openapi.py`, then `git diff --exit-code openapi.json`).
2. **UI second.** `pnpm generate:client` regenerates `src/client/` from `../a11y-health-api/openapi.json` (the path is set in `tools/codegen/openapi-ts.config.ts`; the codegen toolchain is isolated there). It also runs before `pnpm dev`, `pnpm build`, `pnpm typecheck`, and `pnpm test`. Commit the updated `src/client/`.
3. **Fix what the regeneration breaks.** A type break surfaces in `pnpm typecheck`; a response-shape change surfaces as `ZodError` in the route tests (MSW handlers return the old shape until they are updated — update the handler, never mock the SDK).
4. **Flag the cross-repo blocker.** In a single-repo session, the other half is a blocker to name in the summary, not a step to skip: say which repo still needs its half and what command runs it.

## Done when

- `make openapi-check` passes in the API and `openapi.json` is committed beside the code.
- `pnpm typecheck` and `pnpm test` pass in the UI with the regenerated `src/client/` committed.
- From the workspace root, `scripts/sync-skills.sh --check` is clean — a root-touching change is the moment a shared-skill copy is most likely to have drifted. In a single-repo session with no root checked out, this check cannot run: name it in the summary as the root session's step, the same way the other repo's half is named.
