# direct_only is an opt-in refinement of the under_org_unit_id scope, not a new default

`GET /scores/latest?under_org_unit_id=X&direct_only=true` narrows [ADR 0034](0034-under-org-unit-scope-resolves-per-owner-type.md)'s
resolution one step per owner type — `app` serves apps placed exactly on X,
`org_unit` X's depth-1 children, `brand` stays empty — so a client rendering
only a unit's direct rows (the UI's Org Unit detail tables,
a11y-health-ui#57) fetches a response that matches them instead of paging
through the whole subtree. 0034 rejected depth-1 *as the scope's meaning*;
this keeps that default and adds the refinement 0034 anticipated clients
would otherwise do by filtering — which is exactly what didn't survive
contact with keyset pagination: cursor pages are sequential by construction,
so "filter a strict-descendant result" client-side costs one serial
round-trip per page of subtree before first paint, and parallel prefetch is
impossible without an offset/total contract this listing deliberately
doesn't have. Changing 0034's default instead was rejected as a breaking
contract rewrite of a deliberate decision; reverting the UI to id-enumerated
`owner_id` filters was rejected because it reintroduces the two-stage
waterfall the scope exists to remove. The subtree default stays served even
while no in-repo client calls it: it is the scope's recorded meaning, the
form any deeper-than-one view needs, and dropping it would make `direct_only`
the semantics rather than a refinement. `direct_only` without
`under_org_unit_id` is ignored, not a 400 — it refines the scope, no scope
means nothing to refine, and an error mode would buy a new `ErrorCode` for a
well-formed request (the same posture as 0034's brand-scope call).

On a11y-health-ui#57's "adopt only if round trips measurably matter" gate: no
subtree was measured crossing a page boundary before this landed. What was
taken as sufficient instead is structural — the cost is one serial round-trip
per 100 subtree rows *before first paint*, on a listing whose keyset contract
rules out the parallel prefetch that would otherwise absorb it, so the
mitigation cannot be added later without the same contract change plus a UI
rewrite. Being early is bounded here in a way it usually isn't: the parameter
defaults off, changes no existing response, and the subtree default stays the
scope's recorded meaning, so an unused `direct_only` costs one query parameter
rather than a semantics migration.
