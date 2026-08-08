"""A privately named source module or package is reached only from within the
package that owns it.

The underscore is a scope claim, and this is what makes it true: `_foo` may be
reached from its own package — its siblings, and that package's `__init__`,
which *is* the package — and nowhere else. A private *package* gates everything
under it, so a public module cannot serve as a way in. Relative imports resolve
to the same absolute names before the rule is applied, so neither spelling is a
loophole.

The walk covers the installed package, so tests, migrations, and scripts sit
outside the rule — which is what lets a private module's own suite import it
directly.

`_crossings` is the detector and carries its own tests, so the repo-wide
assertion below can't pass by quietly finding nothing.
"""

from collections.abc import Iterable

import a11y_health
from tests.import_graph import imported_modules, package_of, package_sources, packages_in


def _private_gate(module: str) -> str | None:
    """The outermost privately named ancestor on `module`'s path, or the module
    itself — what a caller has to be inside to reach it. `None` when nothing on
    the path is private. Checking the whole path, not just the leaf, is what
    keeps a public module from being a way into a private package."""
    parts = module.split(".")
    for depth, part in enumerate(parts, start=1):
        # The marker is one leading underscore; dunders are the language's, not
        # ours.
        if part.startswith("_") and not part.startswith("__"):
            return ".".join(parts[:depth])
    return None


def _may_reach(importer: str, gate: str) -> bool:
    package = package_of(gate)
    # The gate's siblings may reach it, and so may that package's own
    # `__init__` — which *is* the package, and is where a re-export would live.
    return package == package_of(importer) or package == importer


def _crossings(sources: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    """(importer, gate) pairs where one of `sources`' private modules or
    packages is reached from outside the package that owns it.

    Takes (module name, source) pairs rather than a mapping: two files can
    resolve to one module name, and a mapping drops one of them (#138).
    """
    modules = list(sources)
    packages = packages_in(name for name, _ in modules)
    gates = {gate for name, _ in modules if (gate := _private_gate(name)) is not None}
    found = {
        (importer, gate)
        for importer, source in modules
        for imported in imported_modules(source, importer, packages)
        if (gate := _private_gate(imported)) in gates and not _may_reach(importer, gate)
    }
    return sorted(found)


class TestCrossingDetection:
    def test_private_module_imported_from_another_package_is_a_crossing(self) -> None:
        sources = {"pkg.a._private": "", "pkg.b.consumer": "from pkg.a._private import thing"}

        assert _crossings(sources.items()) == [("pkg.b.consumer", "pkg.a._private")]

    def test_private_module_named_through_its_package_is_a_crossing(self) -> None:
        # `from pkg.a import _private` reaches the same module by the other
        # spelling.
        sources = {"pkg.a._private": "", "pkg.b.consumer": "from pkg.a import _private"}

        assert _crossings(sources.items()) == [("pkg.b.consumer", "pkg.a._private")]

    def test_package_sibling_may_import_a_private_module(self) -> None:
        sources = {"pkg.a._private": "", "pkg.a.sibling": "from pkg.a._private import thing"}

        assert _crossings(sources.items()) == []

    def test_public_module_may_be_imported_from_anywhere(self) -> None:
        sources = {"pkg.a.public": "", "pkg.b.consumer": "from pkg.a.public import thing"}

        assert _crossings(sources.items()) == []

    def test_package_init_may_import_its_own_private_member(self) -> None:
        # A package's `__init__` *is* the package, and re-exporting through it
        # is the reason a private member exists at all.
        sources = {"pkg.a": "from pkg.a._private import Thing", "pkg.a._private": ""}

        assert _crossings(sources.items()) == []

    def test_module_inside_a_private_package_is_a_crossing(self) -> None:
        # The gate is the outermost private name on the path, not the leaf.
        sources = {"pkg._priv": "", "pkg._priv.impl": "", "other.consumer": "from pkg._priv.impl import X"}

        assert _crossings(sources.items()) == [("other.consumer", "pkg._priv")]

    def test_private_package_is_open_to_its_own_package(self) -> None:
        sources = {"pkg._priv": "", "pkg._priv.impl": "", "pkg.consumer": "from pkg._priv.impl import X"}

        assert _crossings(sources.items()) == []

    def test_relative_import_across_packages_is_a_crossing(self) -> None:
        sources = {"pkg.a._private": "", "pkg.b.consumer": "from ..a._private import thing"}

        assert _crossings(sources.items()) == [("pkg.b.consumer", "pkg.a._private")]

    def test_relative_import_within_a_package_is_allowed(self) -> None:
        sources = {"pkg.a._private": "", "pkg.a.sibling": "from ._private import thing"}

        assert _crossings(sources.items()) == []


def test_source_tree_has_no_crossings() -> None:
    modules = package_sources(a11y_health)
    assert any(_private_gate(module.name) for module in modules), "no private modules found — the source walk is broken"

    assert _crossings((module.name, module.source) for module in modules) == []
