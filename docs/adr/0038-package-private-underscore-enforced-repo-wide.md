# A private name is enforced repo-wide, not conventional

A source module or package whose name starts with a single underscore may be reached only from within the package that owns it — its siblings, and that package's own `__init__`, which *is* the package. `tests/test_import_honesty.py` walks the installed package and fails on any crossing, in either import spelling, so the underscore is a checked claim rather than a hint.

Convention alone had already failed. At the moment the rule was written three crossings existed and had survived review: two endpoint modules and a service reaching into `schemas/_tag_parsing.py` and `services/_scoring_vocabulary.py`. Both importers of the latter aliased the marker away (`import _scoring_vocabulary as scoring_vocabulary`), so the violation read as an ordinary import at the call site, and an import-guard test had carved an allowlist exception to legalize it. A name that only review enforces is a name that drifts, and the aliases were the drift made comfortable.

Three scoping decisions are deliberate:

- **The package is the unit, not the layer.** The underscore is Python's own scope marker and the package is the scope it names, so the rule needs no vocabulary of its own. A layer-based rule ("no endpoint may reach a service internal") would have to invent one, and would not describe what the underscore already means to a Python reader.
- **A private package gates everything beneath it.** Otherwise a public module nested inside `_internal/` becomes a way in, and the marker protects only its own file.
- **Tests, migrations, and scripts sit outside the walk.** A private module's own suite has to import it directly; putting test code inside the rule would make the most private modules the least testable.

**Amended 2026-08-06:** the rule above scopes to *modules and packages* — the walk reads file names, and a member's underscore is invisible to it. An underscored **member** of a module (a function, a constant) says the same thing one level down: it is not part of what the module offers its callers, and its external interface is the names left unmarked. That is convention, not a checked claim, and deliberately so — checking it would mean an import graph over symbols rather than files, for a marker whose own suite is the main thing reading past it.

The carve-out above therefore extends: a module's own suite may import its private members, and doing so does not widen the module's interface. #133 turned on this — `tests/_declaration_honesty.py` offers three names to `conftest.py` and its colocated suite reaches three more directly. Judge such an interface by what a *non-test* consumer must learn; a criterion counting importers instead would make any thoroughly-tested private module look public, and would push suites toward testing through a narrower surface than the one they need.

Considered and rejected:

- **Leaving it conventional** — what was in force, and what produced the three crossings this rule closed.
- **A lint rule** (`ruff`'s `TID`/flake8-tidy-imports) — bans relative imports or specific module paths, but cannot express "reachable from its own package only," which is a relation between two modules rather than a property of one.
- **Including test code in the walk** — see above; it inverts the testability of exactly the modules that most need direct tests.

The rule is only as strong as the package structure, and that limit is easy to miss: `services/` is one flat package, so `_latest_snapshot.py` and `_org_subtree.py` are siblings of every resource service and this rule permits all of them to import it. `TestScoringModuleImports` in `tests/test_sibling_imports.py` is what actually holds that line, and only for the modules it names. Privacy inside a flat package is an allowlist question, not an underscore question.

See `docs/architecture.md` ("Underscore means package-private"). [ADR 0031](0031-typed-classification-compact-wire-shape.md)'s 2026-08-05 amendment records the two module moves that made this invariant true; this record covers the generalized rule and its enforcement.
