# Org Unit Rollup cascades; Brand Rollup is flat

The Rollup concept has two distinct implementations and we deliberately did not
unify them:

- **Org Unit Rollup** walks the parent chain and recomputes each ancestor's
  `score_snapshot` as the mean of its children's latest snapshots. Triggered on
  scan completion, scan deletion, app deletion, app reassignment, and org unit
  reparenting.
- **Brand Rollup** aggregates the latest snapshots across every App with a given
  `brand_id`, regardless of where those Apps sit in the org tree. No cascade —
  brands have no hierarchy.

Considered and rejected:
- **A unified "owner rollup" abstraction**: would force brands into a
  single-node tree or invent a parent pointer that is always null. Either way
  the abstraction obscures more than it shares.
- **Brand as a peer node in the org_unit tree**: rejected because brand
  membership is orthogonal to organizational ownership — moving an App between
  org units must not change its brand.

Two rollup paths are the honest model. The duplication in
`scoring_orchestration.py` is intentional.
