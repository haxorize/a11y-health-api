# Filter options are an object keyed by dimension, not a bare array

`GET /scan-runs/{id}/findings/filter-options` returns `{"wcag_criteria": [...]}` —
an object with one field per server-enumerable filter dimension — even though the
payload is a single bounded list and
[ADR 0025](0025-bounded-reference-lists-stay-bare-arrays.md) sends bounded
reference lists over the wire as bare arrays. This is a scoped exception to 0025,
not a revision of it: the object is not a wrapper around one list awaiting
hypothetical metadata (the shape 0025 rejected), it is a keyed multi-dimension
payload in which WCAG criteria happen to be the only dimension whose value set
the server alone can enumerate today — the other four findings-filter dimensions
are closed contract enums the client already reads from the OpenAPI document
(#105, "WCAG criteria first"). A future server-enumerable dimension (e.g.
`rule_ids`) lands as an additive sibling field — a non-breaking contract change —
instead of a new endpoint.

Considered and rejected:

- **Bare array at `/findings/wcag-criteria`** (the pure 0025 shape): every future
  dimension becomes its own endpoint and its own UI round-trip, and renaming or
  aggregating them later is a breaking change; the dimension key would live in
  the URL instead of the schema.
- **Extending `GET /scan-runs/{id}/summary`**: one fewer operation, but the
  summary is a Score Snapshot view — mixing findings-filter enumeration into it
  couples two unrelated read models and forces summary consumers to pay for
  criteria they don't use.
