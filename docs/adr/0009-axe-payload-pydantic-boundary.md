# Axe payload validation lives in Pydantic at the API boundary

> **Amended by [ADR 0022](0022-error-contract-single-table-400-vs-422.md):** the
> boundary decision stands, but validation failures no longer surface as 422s —
> `parse_axe_payload()` wraps them into `InvalidAxePayloadError` (400,
> `invalid_axe_payload`) under the Error Contract.

> **Amended by #77:** "eliminated entirely" below overstated the outcome. The
> raw document kept crossing the service seam as a second argument
> (`raw_payload`, stored as the Page Result's Raw JSON) beside the validated
> Axe Payload, matched to it only by caller convention. #77 closed that
> side-channel: `parse_axe_payload()` is the single sanctioned crossing of the
> axe boundary, and it retains the exact uploaded document on the Axe Payload
> (`source_document`, a property backed by a private attribute, excluded from
> the schema's own serialization), from which the service reads the Raw JSON
> to store.

The axe DevTools JSON shape is fully validated by the `AxePayload` Pydantic
schema at the API boundary, including semantic checks (impact values,
classification tag shape, criteria parsing) — not just structural ones. The
service layer receives a validated `AxePayload` and trusts it. A custom
`InvalidAxePayloadError` previously raised from the service layer was removed
(#55); validation failures surface as 422s through Pydantic's standard error
path.

Considered and rejected:
- **Pass raw `dict[str, Any]` into the service and validate there**: the
  original shape (#25 replaced it). Forced every service helper to defensively
  re-check fields, scattered error formatting, and tempted callers to peek into
  unvalidated dicts. The `dict` path was eliminated entirely once the schema
  could carry the semantic rules.
- **Two-layer validation (Pydantic for shape, service for semantics)**:
  rejected because every "semantic" rule we had — impact must be one of four
  values, classifications must look like `{"standard": ..., "version": ..., "level": ...}`,
  wcag_criteria must parse — was expressible as a Pydantic validator. Splitting
  the rules across layers lost the locality without buying anything.

The boundary is now: outside the schema = unsafe input; inside the service =
trusted, structured payload. New axe payload constraints belong on the schema.

---

**Amended 2026-08-05:** the boundary widens over the document's identity
fields, and the crossing moves behind the service seam. `AxePayload` gains
optional `name` and `endTime` — the two fields the CLI had been reading raw
with hand-rolled checks — strict when present, absent-is-fine; the offset-less
`endTime` UTC assumption moves into the schema's validator, which keeps
today's parser so what parses today keeps parsing. `parse_axe_payload()`
stays the sole sanctioned crossing, but its call site moves from the endpoint
into `create_page_result`'s first statement, so the service owns its
`invalid_axe_payload` error mode and its pending-run precondition (which
moves in from the scan-run service, retiring the services layer's only
sibling import). This revisits "the service layer receives a validated
`AxePayload`" deliberately: what the original decision rejected was
validation *scattered inside* service helpers, and none of that returns —
every rule stays on the schema, and below the crossing only the typed payload
exists; the raw parameter has exactly one reader. The CLI consumes the same
schema at scan load, dropping its raw reads — the one behavior change: a
locally invalid file now fails before any upload, leaving no partial pending
run; the left-pending rule survives for server-only rejections. No bypass
flag: CLI and server ship from one package, so skew means a mismatched
install, and the fix is reinstalling, not preserving the raw-upload side
door. Rejected: a second, shallow crossing for just the identity fields (two
sanctioned crossings where the module promises one), and widening without
moving the crossing (the parse stays caller-remembered and the service still
can't own its error mode).
