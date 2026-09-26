"""Every module under `src/` is reached from an entry point, and the ones
reached only from `tests/` are named.

A transitive closure over `tests.import_graph`'s reading, from the places
execution actually starts — the FastAPI app, the CLI's console script, the
alembic env and its versions, `scripts/`, and the suite. A module outside that
closure is dead: nothing imports it, so no test can be exercising it and no
deploy can be running it. A module inside the closure only because a test
imports it is a seam in the wrong place — `src/` code that exists for the
suite — so that set is pinned by name, and growing it is a reviewed edit here
rather than a quiet drift (ADR 0039).
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path

import a11y_health
from tests.import_graph import (
    Module,
    import_edges,
    imported_modules,
    package_edges,
    package_sources,
    resolved_modules,
    synthetic_module,
)

REPO = Path(__file__).resolve().parent.parent

# Where execution starts. A new script, console entry, or framework hook is
# added here; the closure names nothing else.
PRODUCTION_ENTRIES = frozenset(
    {
        "a11y_health.main",  # the FastAPI app (uvicorn, scripts/export_openapi.py)
        "a11y_health.cli",  # `a11y` console script (pyproject `[project.scripts]`)
    }
)
PRODUCTION_ENTRY_FILES = (
    REPO / "migrations" / "env.py",
    # A data migration imports a helper from `src/` that nothing else may.
    *sorted((REPO / "migrations" / "versions").glob("*.py")),
    *sorted((REPO / "scripts").glob("*.py")),
)
TEST_ENTRY_FILES = tuple(sorted((REPO / "tests").rglob("*.py")))

# Modules under src/ that only the suite reaches. Empty is the target; a name
# here is a known seam, kept until the code moves to where its caller lives.
REACHABLE_ONLY_FROM_TESTS: frozenset[str] = frozenset()


def _closure(
    edges: Mapping[Module, frozenset[str]], entry_names: Iterable[str], entry_files: Iterable[Path]
) -> set[Module]:
    """The modules reached, transitively, from the entries.

    Keyed by `Module`, never by name: two files can resolve to one name (#138),
    and reaching that name reads both sources so neither file's imports are
    lost. `test_name_collisions_are_reported` makes the collision itself a
    failure, since the file Python does not import is dead by construction.
    """
    by_name: dict[str, list[Module]] = defaultdict(list)
    for module in edges:
        by_name[module.name].append(module)

    reached: set[Module] = set()
    frontier: set[str] = set()
    for path in entry_files:
        frontier |= resolved_modules(imported_modules(path.read_text(), importer=path.stem), by_name)
    frontier |= resolved_modules(entry_names, by_name)
    while frontier:
        name = frontier.pop()
        for module in by_name[name]:
            if module in reached:
                continue
            reached.add(module)
            frontier |= resolved_modules(edges[module], by_name)
    return reached


def _names(modules: Iterable[Module]) -> frozenset[str]:
    return frozenset(module.name for module in modules)


class TestClosure:
    # The detector's own cases, on synthetic modules, so the repo-wide
    # assertion below cannot pass by quietly reaching nothing.
    def test_reaching_a_submodule_reaches_its_packages(self) -> None:
        modules = [
            synthetic_module("pkg"),
            synthetic_module("pkg.sub"),
            synthetic_module("pkg.sub.leaf"),
            synthetic_module("pkg.other"),
        ]

        assert _names(_closure(import_edges(modules), {"pkg.sub.leaf"}, ())) == {"pkg", "pkg.sub", "pkg.sub.leaf"}

    def test_an_import_is_followed_and_an_unimported_module_is_not_reached(self) -> None:
        modules = [
            synthetic_module("pkg"),
            synthetic_module("pkg.a", "from pkg import b\n"),
            synthetic_module("pkg.b"),
            synthetic_module("pkg.dead"),
        ]

        assert _names(_closure(import_edges(modules), {"pkg.a"}, ())) == {"pkg", "pkg.a", "pkg.b"}

    def test_an_entry_file_outside_the_package_seeds_the_walk(self, tmp_path: Path) -> None:
        script = tmp_path / "run.py"
        script.write_text("from pkg.a import go\n")
        modules = [synthetic_module("pkg"), synthetic_module("pkg.a"), synthetic_module("pkg.dead")]

        assert _names(_closure(import_edges(modules), (), (script,))) == {"pkg", "pkg.a"}

    def test_both_files_behind_one_name_are_read(self) -> None:
        # A stale `owner.py` beside a new `owner/__init__.py`: whichever file
        # a mapping kept, the other's imports would vanish from the closure.
        stale = Module(Path("/fake/pkg/owner.py"), "pkg.owner", "from pkg import only_stale_imports_me\n")
        fresh = Module(Path("/fake/pkg/owner/__init__.py"), "pkg.owner", "from pkg import only_fresh_imports_me\n")
        modules = [
            synthetic_module("pkg"),
            stale,
            fresh,
            synthetic_module("pkg.only_stale_imports_me"),
            synthetic_module("pkg.only_fresh_imports_me"),
        ]

        reached = _closure(import_edges(modules), {"pkg.owner"}, ())

        assert {stale, fresh} <= reached
        assert _names(reached) >= {"pkg.only_stale_imports_me", "pkg.only_fresh_imports_me"}


def test_name_collisions_are_reported() -> None:
    # Two files resolving to one name: Python imports the package and the
    # module beside it is dead, which no closure keyed by name can see.
    by_name: dict[str, list[Path]] = defaultdict(list)
    for module in package_sources(a11y_health):
        by_name[module.name].append(module.path)
    collisions = {name: sorted(str(p) for p in paths) for name, paths in by_name.items() if len(paths) > 1}
    assert collisions == {}, f"two files resolve to one module name — one of them is dead: {collisions}"


def test_every_module_is_reached_and_the_test_only_seams_are_the_named_ones() -> None:
    edges = package_edges(a11y_health)
    names = _names(edges)
    production = _names(_closure(edges, PRODUCTION_ENTRIES, PRODUCTION_ENTRY_FILES))
    from_tests = _names(_closure(edges, (), TEST_ENTRY_FILES))
    everything = production | from_tests

    # Each walk pinned on a non-empty shape: the app module is an entry and the
    # tree has packages under it, and the suite imports the app too — so an
    # empty `tests/` glob or a typo in its pattern fails here, not silently.
    assert "a11y_health.main" in production
    assert any(name.startswith("a11y_health.api.") for name in production)
    assert len(TEST_ENTRY_FILES) > 0
    assert "a11y_health.main" in from_tests

    unreachable = sorted(names - everything)
    assert unreachable == [], f"modules nothing imports — delete them or add their entry point: {unreachable}"

    only_tests = everything - production
    assert only_tests == REACHABLE_ONLY_FROM_TESTS, (
        "src/ modules reached only from tests/ changed; move the code to its caller or pin the name: "
        f"{sorted(only_tests ^ REACHABLE_ONLY_FROM_TESTS)}"
    )
