# Bounded reference lists stay bare arrays, not paginated envelopes

Four read operations return a bare JSON array instead of the `Page[T]` envelope every other list operation uses: `GET /brands`, `GET /org-units`, and the hierarchy traversals `GET /org-units/{id}/ancestors` and `/descendants`. The asymmetry is deliberate, not drift.

The `Page[T]` envelope (see [ADR 0017](0017-keyset-pagination-deep-module.md)) exists for unbounded, event-like collections — scan runs, findings, page metrics, score history — where rows accumulate without limit and no client should assume one response holds everything. Brands and Org Units are the opposite: reference tables. Brands are a fixed handful of commercial brands; the Org Unit tree is the company's org chart. Their consumers (dropdowns, tree rendering, breadcrumbs) need the whole collection to do their job at all — a paginated org-unit list can't render a tree until the client has looped every cursor, and an ancestors path is bounded by tree depth, where a cursor is meaningless. Wrapping these in an envelope adds unwrap-and-loop ceremony to every consumer without ever changing what is transferred.

Considered and rejected:

- **Adopt the envelope everywhere for uniformity**: one shape for all list operations, but it forces cursor loops onto data that always fits one response, and turns "give me the tree" into a client-side pagination protocol. Uniformity of shape is not worth non-uniformity of consumer effort.
- **A non-paginated envelope (`{"items": [...]}`) without a cursor**: keeps a wrapper for hypothetical future metadata but still breaks every consumer today for a field nobody has asked for.

The boundary is the data's growth model, not its current row count: an operation returns a bare array only when the collection is structurally bounded (reference data, tree traversals). If one of these collections stops being bounded — or a consumer genuinely needs to page it — that operation graduates to the envelope as its own story, since contract shape changes stop being cheap once UI list screens consume them.

---

**Amended 2026-07-21 (#129):** `GET /org-units/{id}/descendants` was removed once its last consumer migrated to the `parent_id` filter on `GET /org-units` — not a graduation to the envelope but a departure from the surface. Three of the four operations remain; the decision stands unchanged for them.
