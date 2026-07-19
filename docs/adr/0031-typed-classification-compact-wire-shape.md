# Typed Classification schema with a compact wire shape

`RuleFindingRead.classifications` is served as a closed typed schema (`standard` enum required; `version`/`level` optional, `level` an A/AA/AAA enum) instead of the open string map it started as, and a model serializer omits absent members so the wire shape stays byte-identical to the stored JSONB (`{"standard": "best-practice"}`, never `"version": null`). Issue #106 proposed plain-string members; the enums were tightened deliberately — values are minted from a fixed server-side token map, so the enum documents reality, and widening it later is a normal contract change through the codegen pipeline. Serializing the model naively was rejected because explicit nulls fail the previously generated UI client's Zod validator (`Record<string, string>`), turning an API-first deploy into a broken findings page; note this narrowing cuts both ways — any future change to this schema (even a widening) breaks already-generated clients until the UI regenerates, so contract edits here are lockstep changes with the UI.

## Consequences

- One canonical Classification shape everywhere: stored JSONB, GIN containment filter targets, and the wire all agree (`Classification.stored()` and the `_omit_none_members` serializer in `models/classification.py`).
- Out-of-vocabulary values in the JSONB column (manual backfill, a future standard) now fail read-side validation instead of passing through — write-side enforcement is a tracked follow-up.

---

**Amended 2026-07-18 (#114):** the follow-up landed, and it changed both halves of the second consequence. The compact shape is now a column guarantee — `_CompactClassifications` (a `TypeDecorator` in `models/rule_finding.py`) validates and dumps every bound value, covering writers and the filter's GIN containment targets alike — and an out-of-vocabulary entry written past that guard (raw-SQL backfill) is dropped from reads with a warning instead of failing the page that renders it, matching the codebase's tolerant-read style (unknown tags dropped at ingest, out-of-shape criteria sorting last). `Classification` itself moved to `models/classification.py`, a layer-neutral leaf, so the column type never imports from schemas; `schemas/_tag_parsing.py` still owns parsing and the token vocabulary.
