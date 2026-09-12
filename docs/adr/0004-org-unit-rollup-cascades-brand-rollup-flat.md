# Org Unit Rollup cascades; Brand Rollup is flat

> **Amended 2026-09-12 (#146):** the two shapes stand, but the argument below no longer describes the code. [ADR 0037](0037-per-owner-variation-concentrates-in-the-owner-dispatcher.md) gave both paths one entrypoint, and the duplication sentence at the foot is retired. See Amendments.

The Rollup concept has two distinct implementations and we deliberately did not unify them:

- **Org Unit Rollup** walks the parent chain and recomputes each ancestor's `score_snapshot` as the mean of its children's latest snapshots. Triggered on scan completion, scan deletion, app deletion, app reassignment, and org unit reparenting.
- **Brand Rollup** aggregates the latest snapshots across every App with a given `brand_id`, regardless of where those Apps sit in the org tree. No cascade — brands have no hierarchy.

Considered and rejected:
- **A unified "owner rollup" abstraction**: would force brands into a single-node tree or invent a parent pointer that is always null. Either way the abstraction obscures more than it shares.
- **Brand as a peer node in the org_unit tree**: rejected because brand membership is orthogonal to organizational ownership — moving an App between org units must not change its brand.

Two rollup paths are the honest model. The duplication in `scoring_orchestration.py` is intentional.

## Amendments

- **2026-09-12 (#146)** — **The decision stands; its rationale was overtaken by [ADR 0037](0037-per-owner-variation-concentrates-in-the-owner-dispatcher.md).** The two shapes are still the model: Org Unit Rollup cascades up the parent chain, Brand Rollup is flat. What changed is that they no longer live as two paths in `scoring_orchestration.py`. That module is a switchboard whose every handler delegates to one `owner.rollup()` entrypoint, and the per-owner difference is carried by `RollupSpec.cascade_parent`, which is `None` for brands. A reader who opens the body above is told the duplication is intentional and then finds no duplication.
- **2026-09-12 (#146)** — **The rejected alternative was narrowed, not reversed, and the distinction is the point.** "A unified owner rollup abstraction" was rejected for forcing brands into a single-node tree or inventing an always-null parent pointer. ADR 0037's dispatcher does neither: a `cascade_parent` of `None` is a flat rollup declared as flat, not a brand pretending to be a tree with a null parent. One entrypoint over two declared shapes is a different thing from one shape imposed on two owners, and that is why this record was not superseded.
- **2026-09-12 (#146)** — **"The duplication in `scoring_orchestration.py` is intentional" is retired.** It was true when written and is false now. The sentence stays as written, because amendments never rewrite; this entry and the pointer at the top are what flag it.
