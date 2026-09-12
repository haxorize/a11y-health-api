# CASCADE for ownership chains, RESTRICT for reference relationships

Foreign keys split into two groups by `ON DELETE` semantics, by intent:

- **CASCADE** — used when the child is owned by the parent and has no meaning without it. `ScanRun.app_id`, `PageResult.scan_run_id`, `RuleFinding.page_result_id`, `NodeFinding.rule_finding_id`, `ScoreSnapshot.app_id`, `ScoreSnapshot.scan_run_id`. Deleting the parent is the operator's intent to remove the whole subtree.
- **RESTRICT** — used when the child references the parent but isn't owned by it. `App.brand_id`, `App.org_unit_id`, `OrgUnit.parent_id`, `ScoreSnapshot.org_unit_id`, `ScoreSnapshot.brand_id`. Deleting a Brand or Org Unit that still has Apps would silently orphan accountability, so the database refuses and the service surfaces a `HasDependentsError` (#19).

Considered and rejected:
- **CASCADE everywhere** (the convenient default): would let a brand deletion silently wipe every app under it. Wrong shape for our domain — brands and org units are accountability boundaries, not lifetime owners.
- **RESTRICT everywhere** (the strict default): would force the API to manually delete every page result and finding before a scan run could be deleted, just to land in the same end state. Pure friction for truly-owned children.
- **SET NULL on RESTRICT-flagged FKs**: rejected because nullable `org_unit_id` / `brand_id` on App breaks the invariant that every App has an owner.

The split is intentional and the names are load-bearing — anyone adding a new FK needs to ask "is this child owned, or just referencing?"
