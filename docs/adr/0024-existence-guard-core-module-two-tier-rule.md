# The Existence Guard is one core module with a two-tier call rule

Checking that a referenced entity exists lives in a single deep module, `core/existence.py`, with two entry points — `get_by_pk` and `get_by_query` — one closed entity→label table, and the only `raise NotFoundError` site in the package. Callers follow a two-tier rule: each entity's own service keeps its named accessor (`get_app`, `get_brand`, …) as a one-line delegation for endpoints, and every other module calls the guard directly, so no service imports a sibling service to ask "does it exist?" (or to fetch an entity it only reads). This replaced seven hand-rolled fetch-then-raise guards and the cross-service import topology they forced — six distinct sibling imports (seven function-local import statements) existed purely to dodge import cycles.

Two placement decisions are deliberate:

- **The guard sits in the service/domain layer (core), not in endpoint dependencies.** Services are entered from the CLI and scoring orchestration as well as from HTTP; the idiomatic FastAPI shape — a `Depends(get_app_or_404)`-style dependency — would silently unguard those paths and put domain logic back in transport. A future reader inclined to "modernize" this into endpoint dependencies is re-proposing the rejected option.
- **`core/existence.py` imports the model classes** — the first core module to do so (`pagination`, `slug`, `exceptions` are model-agnostic). The label table needs the classes as keys, and the dependency is acyclic: models depend only on `core/database`, never on the guard. — amended: see Amendments 2026-09-26

Considered and rejected:

- **Endpoint-dependency guard** (per above): unguards CLI and orchestration entry paths; violates the thin-endpoint rule.
- **A per-service raise helper** that only deduplicates the raise: fixes the seven-fold duplication but leaves the real disease — the cross-service import topology — intact.
- **A call-site label override parameter** (for the "Scan run summary" lookup, whose label is contextual rather than the entity's name): moves not-found wording back out of the module; the closed table keyed by model stays the single source of message text, with `ScoreSnapshot`'s entry documented as the summary-lookup label.

The single raise site is what the Error Contract work (#73) formalizes for the not-found mode. The topology is pinned structurally: AST tests assert `NotFoundError` is raised only from the guard and that no service module contains a function-local import. See `docs/architecture.md` ("The Existence Guard and the two-tier call rule") and, for the shape precedent, [ADR 0017](0017-keyset-pagination-deep-module.md).

## Amendments

- **2026-09-26 (#162)** — The label table now lives beside the error definitions in `core/exceptions.py`, which takes over the model-class imports from the guard; every mode that names an entity takes its model type and resolves its label there, and the guard is one reader among several.
