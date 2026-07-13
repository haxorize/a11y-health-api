# The Integrity Guard classifies by constraint identity inside an engaged savepoint

Integrity-violation → domain-error translation lives in one core module,
`core/integrity.py::guard` (#96), replacing two hand-rolled copies in the Org
Unit and App services. Four decisions in its shape are deliberate:

- **Classify by the driver-parsed constraint identity**
  (`exc.orig.__cause__.constraint_name`), never by matching rendered error
  text. Rendered messages append the bound row values, so data merely
  *containing* a constraint's name could misclassify an unrelated violation,
  and one constraint name embedded in another could collide. The fallback is
  fail-safe: an error with no parsed name re-raises unchanged, so a driver
  swap that moves the attribute degrades recognized conflicts from 409s to
  loud 500s — never to a wrong classification.
- **The guarded mutation goes *inside* the `async with` block.** SQLAlchemy's
  `begin_nested()` flushes pending state *before* emitting SAVEPOINT
  (`SessionTransaction._take_snapshot`), so a write pending at entry fails
  outside the savepoint and poisons the whole transaction — the context-manager
  shape is forced by this, not a style choice. Full diagnosis:
  `docs/solutions/begin-nested-flushes-pending-state-before-savepoint.md`.
- **Violations raised by the entry pre-flush are never classified.** The guard
  only translates once the savepoint is engaged; misuse (mutating before the
  block) surfaces the raw `IntegrityError` rather than a mapped domain error
  the dead savepoint cannot back.
- **Constraint→error mappings are built per call and are single-use** —
  `raise ... from` mutates the instance it raises, so a module-level mapping
  would carry one request's traceback into the next.

Considered and rejected:

- **Message-text matching** (the literal wording of Story #96's AC2): weaker
  than identity for the reasons above; the parsed name satisfies the AC's
  intent — bound values can never spoof — and a dedicated test pins it.
- **A `default=` catch-all** for writes where "any violation means one thing"
  (the Dependents Guard's delete, whose RESTRICT FKs were unnamed): removed in
  favor of naming those FKs (`fk_org_unit_parent_id`, `fk_app_org_unit_id`,
  `fk_score_snapshot_org_unit_id`) and mapping them explicitly. A catch-all
  disguises an unrelated violation as a domain 409, against ADR 0022's rule
  that internal failures surface as 500s.
- **Factory mappings** (`Callable[[], DomainError]`) to remove the single-use
  hazard: a heavier interface at every call site for a hazard the docstring
  and per-call convention already cover.

Pinned by `tests/core/test_integrity.py` (spoof-proofing, raw re-raise on
misuse, transaction-stays-usable). See `docs/architecture.md` ("How errors
become HTTP status codes") and, for the core deep-module precedent,
[ADR 0017](0017-keyset-pagination-deep-module.md) /
[ADR 0024](0024-existence-guard-core-module-two-tier-rule.md).
