# Defer JSONB columns by access pattern, not by column type

JSONB columns in this codebase are split into two groups, and the rule is access-pattern-driven, not type-driven:

- **Deferred** (`deferred(mapped_column(JSONB, ...))`): `PageResult.raw_json` and `NodeFinding.checks`. Large payloads, only needed for drill-down detail views, never present in list responses.
- **Not deferred**: `RuleFinding.classifications`, `RuleFinding.tags`, `RuleFinding.wcag_criteria`. Small payloads, present in every Rule Finding list response. — amended: see Amendments 2026-09-19

Considered and rejected:
- **Defer every JSONB column for safety**: would require `undefer()` on every finding query, since classifications and tags are always rendered. Net-negative ergonomics with no real win.
- **Defer no JSONB columns**: would force every page-result list query to drag full axe payloads (often 10–100 KB each) across the wire.

If a column is read in list views, do not defer it. If a column is large and only read on detail endpoints, defer it. The apparent inconsistency between two JSONB columns on the same model is intentional.

## Amendments

- **2026-09-19 (#152 review)** — **`NodeFinding.target` is a sixth JSONB column, not deferred, and it fits neither case the closing rule names.** The split above was written as exhaustive over five columns. `target` is small, and it is read only on a detail endpoint: no list response carries Node Findings, and the one read that loads them is `get_finding` in `services/rule_finding.py`, which renders `target` for every node it returns. Deferring it would save nothing on any query and add an `undefer()` to that one. So the rule gains its missing case: a column that is small and read only on a detail endpoint is not deferred either, because deferral pays only for a column that is large.
