---
name: contract-change
description: The two-repo procedure for changing the Accessibility Health REST contract — anything `make openapi` rewrites — so the API's OpenAPI spec and the UI's generated client land together. Use when an API change moves `openapi.json` at all, whether that is an endpoint, a schema, a response shape, an operation id, or only a description, when the UI needs a field or operation the generated client lacks, or when `openapi.json` or `src/client/` shows up in a diff.
---

# Contract change

The API is the source of truth and the contract is `a11y-health-api/openapi.json`; the UI consumes it through `@hey-api/openapi-ts` into `a11y-health-ui/src/client/` (types, fetch SDK, Zod response validators, TanStack Query options). Both artifacts are committed so a PR diff shows the contract moving. A change to one side without the other is the drift this procedure exists to prevent, and nothing in either repo reports it until the client is regenerated — which is what step 3 is for.

This file is one copy of three, hash-locked in each subrepo's `skills-sync.lock`: edit it at the workspace root, `.claude/skills/contract-change/SKILL.md`, then run `scripts/sync-skills.sh` there — never edit a subrepo copy.

## Workflow

1. **API first, run from `a11y-health-api/`.** Make the change, then `make openapi` regenerates `openapi.json` deterministically. Operation ids drive the UI's method names — `_operation_id` in `src/a11y_health/main.py` — so a renamed operation is a UI rename too. Commit `openapi.json` in the same change as the code; `make openapi-check` is the drift check, and CI runs that same target. API first holds past the commit for a query param that narrows what an operation returns: the API ignores a param it does not declare without an error, so a UI that sends one before the API reads it gets the wider answer silently: the API change that reads the param lands first, and the UI change that sends it lands after. The worked case is ADR 0016's 2026-09-26 update, `docs/adr/0016-scoped-screens-name-a-place-not-a-list-of-owner-ids.md` inside the UI repo.
2. **UI second, run from `a11y-health-ui/`.** `pnpm generate:client` forces a regeneration of `src/client/`. The spec path has exactly one owner: `scripts/regen-client.sh` defaults it to `../a11y-health-api/openapi.json`, absolutizes it, and exports it as `OPENAPI_SPEC` — `tools/codegen/openapi-ts.config.ts` reads that variable and throws without it, so set the variable rather than editing the config. The codegen toolchain is isolated in `tools/codegen/` and the generator runs with that directory as its cwd (ADR 0020, `docs/adr/0020-codegen-toolchain-isolated-from-native-tsc.md` inside the UI repo — an ADR number alone resolves to a different record in each repo). `predev`, `prebuild`, `pretest`, and `pretypecheck` run the same script unforced, and it skips while its inputs (the spec, `tools/codegen/openapi-ts.config.ts`, and `tools/codegen/pnpm-lock.yaml`) hash the same as at the last successful regeneration on this machine, so only `generate:client` guarantees a fresh client. Commit the updated `src/client/`.
3. **Fix what the regeneration breaks, still in `a11y-health-ui/`.** A type break surfaces in `pnpm typecheck`; a response-shape change surfaces as `ZodError` in the route tests (MSW handlers return the old shape until they are updated — update the handler, never mock the SDK).
4. **Flag the cross-repo blocker.** In a single-repo session, the other half is a blocker to name in the summary, not a step to skip: say which repo still needs its half and what command runs it.

## Done when

- `make openapi-check` passes in the API and `openapi.json` is committed beside the code.
- `pnpm typecheck` and `pnpm test` pass in the UI with the regenerated `src/client/` committed.
- From the workspace root, `scripts/sync-skills.sh --check` is clean against each subrepo's `skills-sync.lock` — a root-touching change is the moment a shared-skill copy is most likely to have drifted. In a single-repo session with no root checked out, this check cannot run: name it in the summary as the root session's step, the same way the other repo's half is named.
