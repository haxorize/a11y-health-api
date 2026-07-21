# The under_org_unit_id scope resolves per owner type: inclusive for apps, strict for org units, empty for brands

`GET /scores/latest?under_org_unit_id=X` names a place in the org tree, not owners, so
each owner type resolves it by its own placement semantics rather than one uniform
subtree rule: `app` serves apps placed anywhere in X's inclusive subtree (an app *of* X
is under X, matching the apps listing's descendant-expanding `org_unit_id`); `org_unit`
serves strict descendants (X is not under itself, and X's own rollup already aggregates
the very subtree being scoped, so including it would answer a different question);
`brand` serves the empty set (brands have no org-tree placement, so the scoped
brand-owner set is honestly empty). Direct-children-only was rejected for the org_unit
form because a depth-1 rule would need a second mechanism the moment any deeper view
lands, while clients wanting depth 1 can filter a strict-descendant result. Rejecting
brand + scope with a 400 was rejected because the combination is a well-formed filter
whose true answer is ∅, not a malformed request — an error mode would buy a new
`ErrorCode` and a special case to protect a client mistake the empty page already makes
visible. The scope composes with the exact-match `owner_id` filter by intersection (both
predicates apply), the same composition as the apps listing's `brand_id` + `org_unit_id`.
