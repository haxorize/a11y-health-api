"""The walk under the topology guards, tested where they cannot test it.

Every guard built on `package_sources` asserts on an empty offender list, so a
file the walk never reads is indistinguishable from a file with nothing to
report. That makes the walk's own coverage the thing to pin, and it has to be
pinned on a **non-empty** expected set — a test asserting "no offenders" over a
tree the walk silently skipped passes for the wrong reason, which is the defect
this file exists to keep closed (#138).
"""

import sys
from pathlib import Path
from types import ModuleType

import pytest

import a11y_health
from tests.import_graph import (
    assert_descends,
    imported_modules,
    module_name,
    package_of,
    package_root,
    package_sources,
    packages_in,
    resolved_modules,
    source_paths_importing,
)

_FORBIDDEN = "from a11y_health.services.owner import rollup\n"


def _fake_package(root: Path, name: str) -> ModuleType:
    """A stand-in for an importable package, so a walk can be pointed at a tree
    built for one test. Only `__file__` and `__name__` are read."""
    package = ModuleType(name)
    package.__file__ = str(root / "__init__.py")
    return package


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    (tmp_path / "__init__.py").write_text("")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "__init__.py").write_text("")
    return tmp_path


def _names_at(root: Path, name: str) -> set[str]:
    return {module.name for module in package_sources(_fake_package(root, name))}


class TestNameCollisions:
    # A stale `owner.py` left on disk beside a new `owner/__init__.py` — the
    # shape a package split leaves behind. Both resolve to `pkg.owner`, so a
    # mapping keyed by module name keeps whichever sorts last.
    def test_both_files_are_read_when_two_resolve_to_one_module_name(self, tree: Path) -> None:
        (tree / "owner.py").write_text("")
        (tree / "owner").mkdir()
        (tree / "owner" / "__init__.py").write_text("")

        paths = {str(m.path.relative_to(tree)) for m in package_sources(_fake_package(tree, "pkg"))}

        assert {"owner.py", "owner/__init__.py"} <= paths

    def test_a_colliding_module_still_reports_its_import(self, tree: Path) -> None:
        (tree / "owner.py").write_text(_FORBIDDEN)
        (tree / "owner").mkdir()
        (tree / "owner" / "__init__.py").write_text("")

        offenders = source_paths_importing(_fake_package(tree, "pkg"), lambda i: any("rollup" in x for x in i))

        assert offenders == ["owner.py"]

    def test_a_colliding_package_init_still_reports_its_import(self, tree: Path) -> None:
        # The direction that actually failed: `owner/__init__.py` sorts first,
        # so keying by name let `owner.py` overwrite it and the offender
        # vanished. Testing one direction only would have missed this.
        (tree / "owner.py").write_text("")
        (tree / "owner").mkdir()
        (tree / "owner" / "__init__.py").write_text(_FORBIDDEN)

        offenders = source_paths_importing(_fake_package(tree, "pkg"), lambda i: any("rollup" in x for x in i))

        assert offenders == ["owner/__init__.py"]


class TestPackageSources:
    def test_module_names_are_dotted_from_the_package(self, tree: Path) -> None:
        (tree / "leaf.py").write_text("")
        (tree / "sub" / "deep.py").write_text("")

        assert _names_at(tree, "pkg") >= {"pkg", "pkg.leaf", "pkg.sub", "pkg.sub.deep"}

    def test_the_walk_descends(self, tree: Path) -> None:
        (tree / "sub" / "deep.py").write_text("")

        assert "pkg.sub.deep" in _names_at(tree, "pkg")

    def test_a_tree_that_does_not_descend_fails_loudly(self, tmp_path: Path) -> None:
        # The complement of the pin: nothing below the top level means the walk
        # cannot be trusted, and every guard on it would pass vacuously.
        (tmp_path / "__init__.py").write_text("")

        with pytest.raises(AssertionError, match="not descending"):
            source_paths_importing(_fake_package(tmp_path, "pkg"), lambda i: True)

    def test_a_namespace_package_is_refused_rather_than_walked_as_empty(self) -> None:
        namespace = ModuleType("ghost")
        namespace.__file__ = None

        with pytest.raises(AssertionError, match="namespace package"):
            package_root(namespace)


class TestRealPackagesStillResolve:
    def test_the_installed_package_walks_and_names_a_known_module(self) -> None:
        # Guards the pairing the old signature could get wrong: a root from one
        # package with another's name yields plausible but wrong dotted names.
        names = {module.name for module in package_sources(a11y_health)}

        assert "a11y_health.core.error_contract" in names
        assert "a11y_health.services.owner" in names

    def test_relative_imports_resolve_against_the_walked_names(self, tree: Path) -> None:
        (tree / "sub" / "sibling.py").write_text("")
        (tree / "sub" / "user.py").write_text("from . import sibling\n")
        modules = package_sources(_fake_package(tree, "pkg"))
        packages = packages_in(module.name for module in modules)
        user = next(m for m in modules if m.name == "pkg.sub.user")

        assert "pkg.sub.sibling" in imported_modules(user.source, user.name, packages)


class TestNamePieces:
    def test_package_init_takes_the_package_name(self, tree: Path) -> None:
        assert module_name(tree / "sub" / "__init__.py", tree, "pkg") == "pkg.sub"

    def test_package_of_is_the_parent(self) -> None:
        assert package_of("pkg.sub.leaf") == "pkg.sub"
        assert package_of("pkg") == ""

    def test_packages_in_names_only_what_something_sits_under(self) -> None:
        assert packages_in(["pkg", "pkg.sub", "pkg.sub.leaf"]) == frozenset({"pkg", "pkg.sub"})


def test_module_is_importable_as_a_sibling() -> None:
    # ADR 0038 puts tests outside the private-name walk, but `import_graph` is
    # public precisely because guards in sibling test packages import it; this
    # pins that it stays reachable as one.
    assert "tests.import_graph" in sys.modules


class TestResolvedModules:
    def test_keeps_only_the_spellings_that_exist(self) -> None:
        known = {"pkg", "pkg.a"}

        assert resolved_modules({"pkg.a.symbol", "pkg.missing"}, known) == {"pkg", "pkg.a"}

    def test_a_submodule_reaches_every_package_above_it(self) -> None:
        known = {"pkg", "pkg.sub", "pkg.sub.leaf"}

        assert resolved_modules({"pkg.sub.leaf"}, known) == known


class TestAssertDescends:
    def test_a_nested_module_passes(self, tree: Path) -> None:
        (tree / "sub" / "deep.py").write_text("")
        modules = package_sources(_fake_package(tree, "pkg"))

        assert_descends(modules, tree)

    def test_a_flat_walk_fails_loudly(self, tmp_path: Path) -> None:
        (tmp_path / "__init__.py").write_text("")
        modules = package_sources(_fake_package(tmp_path, "pkg"))

        with pytest.raises(AssertionError, match="not descending"):
            assert_descends(modules, tmp_path)
