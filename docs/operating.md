# Operating & debugging

How this API is run, checked, and debugged. [ADR 0018](adr/0018-documentation-strategy-prose-over-docstrings.md) gives the behavioral and structural story to [`docs/architecture.md`](architecture.md) and the operating story to this document; its 2026-09-13 amendment records why they are two documents rather than one.

## How a change is checked

Three gates, in the order a change meets them, each recorded where it runs rather than summarized here.

- **The pre-commit hook** (`.githooks/pre-commit`, wired per clone with `git config core.hooksPath .githooks`) scans the staged changes for secrets, then runs lint, the OpenAPI staleness check, and the full suite against a checkout of the index in a throwaway worktree. Why it measures the index rather than the working tree, and the alternatives rejected before it, are [ADR 0046](adr/0046-per-commit-checks-run-against-a-checkout-of-the-index.md).
- **CI** (`.github/workflows/ci.yml`) runs the same lint targets, plus the two Alembic stages the hook cannot: a migration roundtrip and a model/migration drift check, both of which need a live Postgres.
- **The downgrade floor** (`DOWNGRADE_FLOOR` in the `Makefile`) is the revision `make migrate-roundtrip` downgrades to. The comment beside it carries the criterion for raising it and the reason for its current value; read that before lowering it.

## Getting scan data in: the CLI

`cli/` (`uv run a11y …`) is a thin client over the public API, 5 concern modules over one error base ([ADR 0043](adr/0043-onboarding-cli-five-concern-modules-over-one-error-base.md)). Of its 4 commands, 2 are chosen by **App** state:

- **`a11y ingest <dir>`** uploads one **Scan Directory** to an existing **App**. Every JSON file crosses the **Axe Boundary** first, so one the server would reject fails before any upload; then create **Scan Run**, POST each page, PATCH to Completed.
- **`a11y import <dir> --org-unit-id <id> --brand-id <id>`** onboards an **App** from `YYYY-MM-DD/` subdirectories, creating it if missing and uploading each as a **Scan Run**.

The other 2, `a11y org-units` and `a11y brands`, are the lookups behind those ids: `list` and `create` on the first, `list` only on the second.

An **App**'s name and **Slug** are immutable after creation ([ADR 0010](adr/0010-slug-derived-from-axe-name-immutable.md), [ADR 0019](adr/0019-slug-slugified-and-app-identity-locked-at-creation.md)). Every operator-caused failure is a named `CliError` subclass, the only error `main()` catches: it prints one `ERROR:` line and exits 1. Ctrl-C prints `Interrupted.` and exits 130, leaving any Scan Run already created Pending; anything else keeps its traceback.

| Error | Cause |
| --- | --- |
| `AppNotFoundError` | `ingest` on an unimported app |
| `ApiUnreachableError` | server down, or wrong `--base-url` |
| `ApiTimeoutError` | the request timed out |
| `UnreadableApiResponseError` | success status, non-JSON body |
| `NoDateDirsError` | no `YYYY-MM-DD/` subdirectories |
| `NameResolutionError` | missing `name`, or names deriving to different slugs |
| `NameOverrideMismatchError` | `import --name` deriving elsewhere |
| `MissingScanDirectoryError` | no such directory |
| `EmptyScanDirectoryError` | no `*.json` inside |
| `MalformedScanFileError` | not valid JSON or UTF-8 |
| `InvalidScanFilesError` | JSON, but not an axe document |
| `UnderivableAppNameError` | a name with no usable slug |
| `ApiError` | a coded error body from the API |

## Tracing a request

Endpoint (`api/v1/endpoints/`), then service (`services/`), then model. A failing request surfaces as a JSON `{"code": …, "message": …}` body, the **Error Contract**'s `ErrorBody`. Map the code back through the [`ERROR_MODES` table](architecture.md#how-errors-become-http-status-codes), then grep for where that exception is raised.

## Inspecting the data

- Every **Page Result** keeps the full uploaded document as **Raw JSON** (JSONB) for reprocessing, loaded only on demand ([ADR 0008](adr/0008-defer-jsonb-by-access-pattern.md)).
- **Set `DEBUG=true`** (see `config.py`) to echo every SQL statement the engine runs.
- **`GET /api/v1/health`** is the liveness check; Swagger UI is at `/docs` and ReDoc at `/redoc`.
- **`scripts/race_loop.sh`** reruns a suite until it goes red and saves the output, for a failure that will not reproduce under capture.
