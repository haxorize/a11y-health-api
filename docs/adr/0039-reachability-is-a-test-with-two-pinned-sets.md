# Reachability is a test with two pinned sets, and deptry owns dependencies

`tests/test_reachability.py` extends the walker in `tests/import_graph.py`
with a transitive closure from the entry points — the FastAPI app module,
`migrations/env.py`, `scripts/*`, and `tests/` — and asserts two sets. A
module reachable from nothing fails the test. A module reachable only from
`tests/` is collected as its own named set and pinned, to empty or to a listed
set, because code in `src/` that exists for tests is a seam in the wrong
place, and a pinned set is the guard against a walk that silently skipped a
tree, the defect `test_import_graph.py` exists to keep closed. Unused
dependencies are `deptry`'s job, run from `make lint` and the pre-commit hook;
nothing in-house covered that gap and it was not worth writing.

vulture was rejected: confidence-scored heuristics and a whitelist file run
against the repo's precedent of conventions enforced as tests (ADR 0038), and
the repo already owns the AST walker vulture would duplicate. Unused-export
detection is deferred, not rejected: it needs module-level public-name
extraction, an attribute walk keyed by import aliases, and an exemption list
for names reached through registries (route functions, models via metadata,
pytest fixtures), and that list is not worth building until the reachability
test has been green long enough to show the shape of the exemptions.

Accepted costs: a new dev dependency; a module that is legitimately test-only
must be added to the pinned set by hand, which is the reviewable moment; and
the entry-point list is itself a claim that drifts when a new script or
entry appears, so the test names it in one place.
