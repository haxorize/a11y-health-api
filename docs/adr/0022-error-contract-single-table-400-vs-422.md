# Error Contract: one table drives handlers, statuses, codes, and declarations; 422 is framework-only

The contract declared only success statuses and the framework's
request-validation error, while runtime mapped seven domain error modes onto
404/409/400 through an app-level table the OpenAPI document never saw — the
generated client told the UI that only a 422 could occur, which was false for
nearly every operation. A second gap hid behind the same status: an invalid
axe payload returned 422 with a custom body shape the contract also never
declared.

Decided: `core/error_contract.py` owns the entire domain-error → HTTP story in
one table (`ERROR_MODES`), keyed by exception type. Each mode gets exactly one
machine-readable `ErrorCode` from a closed vocabulary; the runtime handler
(registered once for the `DomainError` base; lookup is exact by exception
type, since the exhaustiveness test guarantees every subclass its own row),
the shared `ErrorBody` body (`{"code", "message"}`), and each operation's
OpenAPI declaration (`error_responses(...)`, which also embeds the code set as
`x-error-codes`) all derive from that table, so a wrong status is structurally
impossible. The residual risk — forgetting to declare a mode on an operation —
is closed by enforcement rather than review vigilance: an exhaustiveness test
fails if any `DomainError` subclass lacks a table entry, and a suite-wide
declaration-honesty shim fails any test that observes an undeclared 4xx status
or error code. Table gaps are thus closed structurally; per-operation
declaration gaps are closed as deep as the suite exercises each operation's
error paths — a raisable mode no test triggers stays invisible to the shim.

The transport rule: **422 belongs to the framework** — it is produced only by
FastAPI's own request-shape validation, with its standard body. A request that
is well-formed but fails domain validation (malformed cursor, invalid axe
payload) returns **400 with a coded body**. There is no app-level handler for
Pydantic's `ValidationError`; an internal validation failure escaping the
domain surfaces as a 500, never a disguised client error.

This amends [ADR 0009](0009-axe-payload-pydantic-boundary.md)'s claim that axe
payload validation failures surface as 422s through Pydantic's standard error
path. The boundary decision itself stands — validation still lives entirely in
the `AxePayload` schema — but the transport presentation changes:
`parse_axe_payload()` wraps the schema's `ValidationError` into
`InvalidAxePayloadError`, a first-class domain error mode (400,
`invalid_axe_payload`), keeping one body shape per status per operation.

Considered and rejected:

- **Hand-writing `responses=` declarations per operation with literal
  statuses**: re-scatters the status knowledge the table just concentrated,
  and nothing enforces that a declaration exists or matches runtime — the
  drift this decision exists to kill.
- **Raising transport exceptions (`HTTPException`) from services**: breaks the
  thin-endpoint layering (services would know HTTP), and still doesn't reach
  the contract — the OpenAPI document can't see raised exceptions.
- **Keeping invalid axe payloads on 422**: preserves the status but forces two
  body shapes behind one status on one operation (framework list-body vs.
  coded body), so clients could no longer narrow on the status alone.
