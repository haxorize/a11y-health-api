# Keyset pagination is one deep `paginate()` module

Cursor pagination lives in a single deep `paginate(session, stmt, *, keyset,
cursor, limit, into=None)` in `core/pagination.py`, not as a keyset dance
re-hand-rolled in each list service. Callers pass a pre-filtered `Select` plus
the keyset columns; `paginate` derives cursor arity and per-column type coercion
from those columns for the keyset types in use (`int`, `datetime` ↔ ISO string,
`str`) and raises on any other column type rather than silently passing a raw
JSON scalar through, applies the row-value `WHERE`,
`ORDER BY`, `limit + 1`, `has_more`, slice, and `next_cursor` encode. It supports
both single-column (`[App.id]`) and composite (`[snapshot_at, id]`) keysets behind
one interface, so the implicit `expected=1`/`expected=2` cursor contract disappears.

Two shape decisions are deliberate:

- **An optional `into: Callable[[Row], T]` row→item transform.** Four list sites
  return ORM scalars (default passthrough); `list_page_metrics` returns aggregate
  `Row` tuples it maps into `PageMetricsRead`. Both shapes are real (4 vs 1), so the
  callback is a genuine seam, not speculative indirection.
- **Cursor values are recovered from the SQL row, not the returned item.** The
  keyset drives the cursor; `into` only shapes items. This keeps paging correct
  regardless of what `into` produces, instead of coupling the cursor to an `id`
  attribute the transform must remember to preserve. The precondition this trades
  in: each keyset column's owning entity must appear in the result row as an ORM
  instance (true for `select(Entity)` and `select(Entity, agg, ...)`); a bare
  scalar keyset column is unsupported and raises rather than mis-paging.

Considered and rejected:
- **A `Paginator` class configured per entity**: the statement varies on every call,
  so a per-entity object holds no useful state — a type per list with no behavior
  the function lacks.
- **Homogenizing `list_page_metrics`** (paginate `PageResult` scalars, then a second
  query for the counts): trades the single grouped query for a worse two-query shape
  purely to avoid the optional `into` argument.
- **Leaving `list_page_metrics` out** of the shared module: leaves the most intricate
  cursor site un-absorbed.
- **Reading the cursor off the built item** (`items[-1].id`): simpler, but couples the
  cursor field to an attribute every `into` must preserve, so an exotic transform
  silently breaks paging.

Forward-only, `id`-tiebroken keysets; ascending by default, with opt-in
descending (see the 2026-07-07 addendum below). Cursor mechanics are tested once
in a central `paginate` suite; per-endpoint tests keep only their own assertions. [ADR 0021](0021-domain-rules-test-once-at-the-service-seam.md)
later extended this test-once precedent to the whole suite: filter semantics now
live at the service seam, and per-endpoint tests keep only transport slots.

Story #80 later deepened the module to own the request-facing half as well: the
shared `PageParams` parameter definition (page-size bounds and default) and the
suite-wide rule that any cursor-accepting operation declares the `invalid_cursor`
mode. See `docs/architecture.md` ("Pagination") for that half, including why
`PageParams` is a `Depends()` dependency rather than a `Query()` parameter model.

**2026-07-07 — descending support added.** `paginate()` gained a
`descending: bool = False` argument that reverses both the `ORDER BY` and the
row-value keyset comparison (`< bound` instead of `> bound`); cursor encoding is
unchanged and direction-agnostic. This revisits the "reverse paging is out of
scope" line above. Motivation: history views render in server order (the UI does
not sort client-side), so a Scan Run history table needs newest-first at the
source — `list_scan_runs` now pages `keyset=[ScanRun.scanned_at, ScanRun.id],
descending=True`. Direction is baked per-operation, not a request parameter (no
new query param, no contract change); a client-facing `order` flag stays a future
additive option. Trend lists (`list_app_scores`) stay ascending — correct for a
left-to-right chart.
