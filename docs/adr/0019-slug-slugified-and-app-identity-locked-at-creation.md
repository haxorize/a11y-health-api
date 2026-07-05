# Slug is derived by slugification and App identity is locked at creation

Extends [ADR 0010](0010-slug-derived-from-axe-name-immutable.md), which recorded
that slugs are derived from the axe JSON `name` and immutable — but the code
drifted: the create contract exposed `slug` as a free operator field, the CLI
posted the raw name verbatim as the slug (no slugification, despite DOMAIN.md's
"URL-friendly"), and `name` stayed mutable after creation, letting an App's name
walk away from its slug and from every stored payload.

Decided: the create contract accepts `name` only, and the server derives the
slug through one shared derivation function — NFKD-folded to lowercase ASCII,
non-alphanumeric runs collapsed to single hyphens, ends trimmed (`"My App
(Prod)"` → `my-app-prod`). A name that derives to empty is rejected at the
schema (422, per the schema-validator rule in [ADR 0009](0009-axe-payload-pydantic-boundary.md)).
`name` is dropped from the update contract, so the invariant
`slug == derive(name)` holds **by construction** — both fields are fixed at
creation and no code path can create drift between an App, its slug, and the
`name` recorded in its Scan Runs' Raw JSON. The CLI imports the same derivation
function (same package) before its by-slug lookup, preserving the "raw axe name
in → same App out" round-trip. A one-time data migration re-derives all
existing slugs in place and fails loudly if two rows collide post-derivation.

Considered and rejected:

- **Verbatim slug (slug = raw name, made official)**: no collision widening,
  but retires DOMAIN.md's "URL-friendly" and leaves slugs percent-encoded in
  every URL, including the UI's future routes.
- **Operator-supplied slug validated against the derivation**: the interface
  keeps a field the caller isn't allowed to choose, plus an error mode for
  guessing wrong — maximum interface, zero capability.
- **Canonicalizing lookups instead of creation** (accept raw names at the
  by-slug endpoint): creates URL aliasing and leaves the operator-chosen slug
  drift untouched.
- **Re-deriving the slug when the axe name changes**: reopens ADR 0010 head-on;
  renames would silently rebind scan history — the exact failure 0010 exists to
  prevent. Config renames keep surfacing as new Apps.
- **Rewriting stored Raw JSON to track renames**: falsifies the historical scan
  record kept for reprocessing ([ADR 0008](0008-defer-jsonb-by-access-pattern.md)).
  Derivation is what makes rewriting unnecessary: historical payloads keep
  resolving to the same App because `derive(name)` is deterministic.

Consequences: distinct names that derive to the same slug collide as a loud 409
at creation rather than silently sharing an App — accepted, in the spirit of
0010's "collisions surface rather than silently rebind." Renaming an App is no
longer possible through the API; if a display name ever needs to vary from
identity, that is a new, separately-decided field.

**Amended 2026-07-05 (story #74, AC10):** Import takes an optional
operator-supplied display name, applied only when it creates the App and only
when it derives to the same slug as the axe JSON `name` (a mismatch fails
loudly before anything is created); against an existing App it is ignored with
a warning. The App's name and the Raw JSON `name` may therefore differ in
presentation (casing, punctuation) but never in identity — the invariant held
by construction is precisely `slug == derive(name) == derive(raw JSON name)`,
with both identity fields still fixed at creation and rename still impossible.
This is not the "separately-decided display-name field" above: the override
cannot vary from identity, only prettify within its derivation-equivalence
class.
