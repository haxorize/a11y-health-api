# WCAG criteria stored as a JSONB array on Rule Finding, not via a join table

A Rule Finding maps to zero or more WCAG success criteria (e.g., `["1.1.1"]`, `["1.4.3", "1.4.6"]`). These are stored inline as a JSONB array column with a GIN index, queried with PG containment operators. There is no `wcag_criterion` table and no `rule_finding_wcag_criterion` join table.

Considered and rejected:
- **Relational join table** (`rule_finding_wcag_criterion`): the textbook shape. Rejected because criteria are read with the finding 100% of the time (every list and detail response includes them), and we never query for "all findings on criterion X" via a join — we filter by containment (`wcag_criteria @> '["1.4.3"]'`). The join table would add a JOIN to every finding read for no read benefit.
- **Single text column with the canonical criterion** (the original shape, pre-#51): forced one-to-one mapping when the source data is one-to-many, silently dropping criteria. Replaced by the JSONB array.
- **Separate `wcag_criterion` reference table referenced by ID**: would enforce that values come from a known list, but axe is the source of truth and the list of criteria is stable enough that an enum/reference table is overhead.

The GIN index makes containment filters cheap, and storing criteria with the finding keeps reads single-row.

---

**Amended 2026-07-16 (#105):** the read patterns have evolved past the text above; the decision — JSONB array over a join or reference table — stands. The findings filter accepts several criteria and matches with the any-key operator (`wcag_criteria ?| array[...]`, SQLAlchemy `has_any`) rather than `@>` containment, since a multi-value filter needs OR semantics; the default GIN opclass serves it. And the Filter Options enumeration reads the arrays of one run's findings and dedupes in application code (ADR 0030) — a run-bounded scan that uses no JSONB operator at all. — amended: see Amendments 2026-09-26 (#166)

**Amended 2026-09-26 (#166):** the Filter Options enumeration no longer dedupes in application code. `list_filter_options` in `services/rule_finding.py` is one statement that returns one row: Postgres expands each run's arrays with `jsonb_array_elements_text` and `jsonb_array_elements`, skips a value that is not an array behind a `jsonb_typeof` guard, and dedupes with `DISTINCT` inside `array_agg` and `jsonb_agg`. So the read now runs in JSONB functions rather than none at all; it is still bounded to one Scan Run, and none of those functions is an operator the GIN index serves. The decision, JSONB array over a join or reference table, is unchanged.
