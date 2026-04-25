# App slug is derived from the axe DevTools JSON `name` field and is immutable

An App's `slug` is computed from the `name` field in the axe DevTools JSON at
ingest or import time, not chosen by an operator. Once an App exists, its slug
never changes — the slug is the App's stable external identity, used by
`a11y ingest` to resolve which App a scan directory belongs to.

Considered and rejected:
- **Operator-provided slug**: the obvious choice. Rejected because it forces
  every `ingest` invocation to specify the App, even though the JSON already
  identifies it unambiguously. The CLI workflow is "point at a directory and
  it figures out the App" — that breaks if slug is a separate input.
- **Mutable slug**: rejected because slug is the link between filesystem layout
  (scan directories), CLI commands (`a11y ingest`), and the database. Renaming
  it would silently orphan historical scan directories from their App.

The cost is real: if axe ever changes how it derives `name`, or if a team
renames their app in the test config, the App identity breaks. That's an
acceptable risk given the alternative — and the immutability invariant is what
keeps it acceptable, since rename collisions surface as new Apps rather than
silently rebinding history.
