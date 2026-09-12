# ScoreSnapshot owner is one of {app, org_unit, brand}, enforced by a mutex CHECK

`score_snapshot` carries three nullable FKs — `app_id`, `org_unit_id`, `brand_id` — with a CHECK constraint requiring exactly one to be non-null (`ck_score_snapshot_owner`). All three owner kinds share the same metric columns (score, total_violations, per-page averages, etc.) and the same "latest snapshot per owner" query shape. — amended: see Amendments 2026-09-12

Considered and rejected:
- **Three separate tables** (`app_score_snapshot`, `org_unit_score_snapshot`, `brand_score_snapshot`): would triple migrations, indexes, and rollup query variants for identical columns and identical access patterns.
- **Single-table inheritance with a discriminator**: adds an enum column without removing the need for nullable FKs, since each owner kind still needs its own foreign key.

The mutex CHECK keeps the table polymorphic without losing referential integrity, and lets the latest-snapshot-per-owner selection (`snapshot_at DESC, id DESC`) keep one shape across all three rollup paths.

## Amendments

- **2026-09-12 (#146)** — The shared columns are the Score and four raw counts, not the "per-page averages" the sentence above names. [ADR 0027](0027-score-snapshot-raw-counts-only.md) dropped the derived columns in #93, so the set is `score`, `total_violations`, `pages_with_violations`, `pages_with_critical_violations`, and `total_pages`. The mutex decision is untouched; only its aside had gone stale.
