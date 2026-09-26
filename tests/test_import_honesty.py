"""A privately named source module or package is reached only from within the
package that owns it.

[ADR 0038](../docs/adr/0038-package-private-underscore-enforced-repo-wide.md) is
the record this rests on: the package as the unit, a private package gating
everything under it, both import spellings, and the tests, migrations, and
scripts that sit outside the walk. Inside one flat package the rule permits
every sibling, so which modules should reach a private sibling is
`test_sibling_imports.py`'s question.

`_private_module_imports` is the detector and carries its own tests, so the
repo-wide assertion below can't pass by quietly finding nothing.
"""

from collections.abc import Mapping

from tests.import_graph import Module, package_of, synthetic_edges


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


def _private_module_imports(edges: Mapping[Module, frozenset[str]]) -> list[tuple[str, str]]:
    """(importer, gate) pairs where one of the tree's private modules or
    packages is reached from outside the package that owns it."""
    gates = {gate for module in edges if (gate := _private_gate(module.name)) is not None}
    found = {
        (module.name, gate)
        for module, imports in edges.items()
        for imported in imports
        if (gate := _private_gate(imported)) in gates and not _may_reach(module.name, gate)
    }
    return sorted(found)


class TestPrivateModuleImportDetection:
    def test_private_module_imported_from_another_package_is_reported(self) -> None:
        sources = {"pkg.a._private": "", "pkg.b.consumer": "from pkg.a._private import thing"}

        assert _private_module_imports(synthetic_edges(sources)) == [("pkg.b.consumer", "pkg.a._private")]

    def test_private_module_named_through_its_package_is_reported(self) -> None:
        # `from pkg.a import _private` reaches the same module by the other
        # spelling.
        sources = {"pkg.a._private": "", "pkg.b.consumer": "from pkg.a import _private"}

        assert _private_module_imports(synthetic_edges(sources)) == [("pkg.b.consumer", "pkg.a._private")]

    def test_package_sibling_may_import_a_private_module(self) -> None:
        sources = {"pkg.a._private": "", "pkg.a.sibling": "from pkg.a._private import thing"}

        assert _private_module_imports(synthetic_edges(sources)) == []

    def test_public_module_may_be_imported_from_anywhere(self) -> None:
        sources = {"pkg.a.public": "", "pkg.b.consumer": "from pkg.a.public import thing"}

        assert _private_module_imports(synthetic_edges(sources)) == []

    def test_package_init_may_import_its_own_private_member(self) -> None:
        # A package's `__init__` *is* the package, and re-exporting through it
        # is the reason a private member exists at all.
        sources = {"pkg.a": "from pkg.a._private import Thing", "pkg.a._private": ""}

        assert _private_module_imports(synthetic_edges(sources)) == []

    def test_module_inside_a_private_package_is_reported(self) -> None:
        # The gate is the outermost private name on the path, not the leaf.
        sources = {"pkg._priv": "", "pkg._priv.impl": "", "other.consumer": "from pkg._priv.impl import X"}

        assert _private_module_imports(synthetic_edges(sources)) == [("other.consumer", "pkg._priv")]

    def test_private_package_is_open_to_its_own_package(self) -> None:
        sources = {"pkg._priv": "", "pkg._priv.impl": "", "pkg.consumer": "from pkg._priv.impl import X"}

        assert _private_module_imports(synthetic_edges(sources)) == []

    def test_relative_import_across_packages_is_reported(self) -> None:
        sources = {"pkg.a._private": "", "pkg.b.consumer": "from ..a._private import thing"}

        assert _private_module_imports(synthetic_edges(sources)) == [("pkg.b.consumer", "pkg.a._private")]

    def test_relative_import_within_a_package_is_allowed(self) -> None:
        sources = {"pkg.a._private": "", "pkg.a.sibling": "from ._private import thing"}

        assert _private_module_imports(synthetic_edges(sources)) == []


def test_source_tree_has_no_private_module_imports_from_outside(source_edges: Mapping[Module, frozenset[str]]) -> None:
    found_private = any(_private_gate(module.name) for module in source_edges)
    assert found_private, "no private modules found — the source walk is broken"

    assert _private_module_imports(source_edges) == []
