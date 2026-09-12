# Score Snapshot carries raw counts, not derived display metrics

A Score Snapshot stores the Score and four raw counts (total pages, total violations, pages with violations, pages with critical violations) — and nothing derived from them. Three derived per-page metrics (`avg_violations_per_page`, `pct_pages_with_violations`, `pct_pages_with_critical_violations`) were dropped from the model and the contract in #93.

The derived fields carried zero independent information: every snapshot stores the numerator and denominator they were computed from. What they did carry was a trap — `pct_*` names over 0–1 fraction values. That percentage-named-fraction shape already produced one shipped UI display bug for the similarly-scaled Score, and test fixtures had invented impossible values for these fields (derived values that contradicted the counts in the same row) without anything failing. On rollups they were also a second lens: recomputed from summed counts while the headline score is the unweighted mean of children's scores, so one record stored two aggregations that legitimately disagree.

Considered and rejected:

- **Rename with a truthful fraction-style suffix**: keeps the values queryable in SQL and fixes the names, but costs the same breaking migration while preserving the redundancy and the fixture-can-contradict-the-counts problem.
- **Rescale the values to match the percentage names**: no rename, but keeps the redundancy and diverges from the Score's established 0–1 wire scale, trading one inconsistency for another.

The boundary: snapshots store observations, not presentations. A value derivable from columns in the same row doesn't get a column, and a derived value whose scale a reader must guess doesn't go on the wire — consumers (the UI, SQL, a report) derive shares and averages from the counts at whatever scale their display calls for. The Score itself stays: it is the one derived value with a declared definition (the Scoring Vocabulary, [ADR 0020](0020-scoring-vocabulary-runtime-endpoint.md)) and a documented 0–1 wire scale, and rollups aggregate it rather than recompute it.
