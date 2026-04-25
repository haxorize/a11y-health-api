# Promote Brand from enum to first-class table

Brand started as a Python enum (Humana, CenterWell, Go365, CarePlus, Reliance) on
the `app` model. When brand-level score rollups were added (#31), brands needed
to be queryable, joinable, and own their own `score_snapshot` rows — none of
which an enum supports cleanly. #32 promoted Brand to a `brand` table with a
`brand_id` FK on `app` and a `brand_id` FK on `score_snapshot`.

Considered and rejected:
- **Keep the enum, denormalize brand rollup state**: would have required a side
  table keyed by enum value, which is functionally a brand table without
  referential integrity.
- **Store brand as free-text**: rejected because the set is closed and managed,
  and we want FK-enforced consistency.

The enum-to-table migration is the kind of move that's easy to defer until it
hurts; recording it here so the cost is visible the next time a similar fixed
set ("region", "product line") is added.
