# The brand_id scope resolves per owner type: the brand's apps, empty for org units and brands

`GET /scores/latest?brand_id=B` — the placement-blind twin of the
`under_org_unit_id` scope ([ADR 0034](0034-under-org-unit-scope-resolves-per-owner-type.md))
— names a *brand*, not owners, so each owner type resolves it by its own
ownership semantics: `app` serves the apps whose `brand_id` is B wherever they
sit in the org tree (the same flat `App.brand_id` membership the Brand Rollup
aggregates, so the scope and the rollup can never disagree about which apps a
brand owns); `org_unit` serves the empty set (org units carry no brand); and
`brand` serves the empty set too — **including B itself**. A brand is not owned
by a brand, and B's own rollup is precisely the aggregate of the apps being
scoped to, so serving it here would answer a different question than the one
asked; it is fetched by `owner_id=B`, the exact-match filter that already means
"this owner's row". That mirrors 0034's "X is not under itself" and keeps both
scopes reading as *places to look for owners* rather than owners.

Empty rather than 400 for the non-`app` owner types, for 0034's reason
unchanged: the combination is a well-formed filter whose true answer is ∅, not
a malformed request, and an error mode would buy a new `ErrorCode` plus a
special case to protect a client mistake the empty page already makes visible.

**`brand_id` composes with `owner_id` and `under_org_unit_id` by intersection,
not mutual exclusivity.** #128 floated exclusivity as a semantic to pin down;
it was rejected because every other multi-filter surface in this API already
intersects — 0034's scope with `owner_id`, the apps listing's `brand_id` with
`org_unit_id` — so exclusivity would make this one operation the exception, and
enforcing it means the same new `ErrorCode` the paragraph above declines. The
intersection is also the useful reading: "this brand's apps within this
subtree" is a question the UI's Brand and Org Unit views can both ask, and
"this brand's apps, of these ids" is how a client narrows a known set without a
second request.

See `docs/architecture.md` ("The scoring & rollup model") for where this sits
in the scores-read surface.
