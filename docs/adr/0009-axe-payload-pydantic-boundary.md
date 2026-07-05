# Axe payload validation lives in Pydantic at the API boundary

> **Amended by [ADR 0022](0022-error-contract-single-table-400-vs-422.md):** the
> boundary decision stands, but validation failures no longer surface as 422s —
> `parse_axe_payload()` wraps them into `InvalidAxePayloadError` (400,
> `invalid_axe_payload`) under the Error Contract.

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
  values, classifications must look like `{"id": ..., "version": ...}`,
  wcag_criteria must parse — was expressible as a Pydantic validator. Splitting
  the rules across layers lost the locality without buying anything.

The boundary is now: outside the schema = unsafe input; inside the service =
trusted, structured payload. New axe payload constraints belong on the schema.
