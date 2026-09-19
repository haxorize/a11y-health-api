# Defer JSONB columns by access pattern, not by column type

JSONB columns in this codebase are split into two groups, and the rule is access-pattern-driven, not type-driven:

- **Deferred** (`deferred(mapped_column(JSONB, ...))`): `PageResult.raw_json` and `NodeFinding.checks`. Large payloads, only needed for drill-down detail views, never present in list responses.
- **Not deferred**: `RuleFinding.classifications`, `RuleFinding.tags`, `RuleFinding.wcag_criteria`, and `NodeFinding.target`. Small payloads, present in every Rule Finding or Node Finding list response.

Considered and rejected:
- **Defer every JSONB column for safety**: would require `undefer()` on every finding query, since classifications and tags are always rendered. Net-negative ergonomics with no real win.
- **Defer no JSONB columns**: would force every page-result list query to drag full axe payloads (often 10–100 KB each) across the wire.

If a column is read in list views, do not defer it. If a column is large and only read on detail endpoints, defer it. The apparent inconsistency between two JSONB columns on the same model is intentional.
