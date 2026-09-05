"""Sibling-import rules: inside one package, which modules may import which of
their siblings. Two classes enforce them — an allowlist of the siblings each
scoring module may reach, and a decoupling pin that every resource service
imports nothing from scoring directly. The services layer is the only package
with such rules today; the next sibling-import rule lands here, and nothing
else does. The repo-wide private-module rule is the sibling
`test_import_honesty.py` (ADR 0038); the rules here are motivated in
architecture.md, "The Existence Guard and the two-tier call rule".
"""

import ast
import importlib
import inspect
from types import ModuleType

import pytest

import a11y_health
from tests.import_graph import imported_modules, package_sources, packages_in

_PACKAGE = "a11y_health.services"
_SCORING = {"owner", "score_snapshot"}


def _sibling_service_imports(module: ModuleType) -> set[str]:
    # The shared walk resolves every spelling, relative ones included, to
    # absolute names; this rule keeps the ones under the services package and
    # reads the sibling off each. A bare package import — `import
    # a11y_health.services` or `from a11y_health import services` — would
    # reach a sibling by attribute where no name for the filter to see, so it
    # is refused outright rather than filtered. The walk reports the bare
    # `from` form as the root package, and only the `import` form needs the
    # syntax tree.
    source = inspect.getsource(module)
    imported = imported_modules(source, module.__name__, packages_in(m.name for m in package_sources(a11y_health)))
    imports_package_bare = a11y_health.__name__ in imported or any(
        isinstance(node, ast.Import) and any(alias.name == _PACKAGE for alias in node.names)
        for node in ast.walk(ast.parse(source))
    )
    assert not imports_package_bare, f"{module.__name__} imports the services package bare — name the sibling instead"
    return {name.removeprefix(f"{_PACKAGE}.").split(".")[0] for name in imported if name.startswith(f"{_PACKAGE}.")}


def test_the_filter_reads_a_known_sibling_import() -> None:
    # Every decoupling pin below asserts on an empty intersection, which
    # cannot tell "imports nothing from scoring" from "the walk or the filter
    # returned nothing" — and some resource services really import no sibling,
    # so the helper cannot refuse an empty set itself. One known import pins
    # the reading instead, on the principle `import_graph.assert_descends`
    # states for the walk.
    module = importlib.import_module("a11y_health.services.score_snapshot")

    assert "owner" in _sibling_service_imports(module)


class TestScoringModuleImports:
    # Entity fetches go through the Existence Guard, not a sibling service (see
    # architecture.md, "The Existence Guard and the two-tier call rule"): a
    # scoring module may cross the services namespace only for the siblings
    # named here — shared helpers, the Owner Dispatcher, and for the Rollup
    # trigger the score compute it drives — never a sibling resource service.
    # The rule is which siblings a scoring module may reach, not whether their
    # names are private. Privacy is no help inside `services/`: it is one flat
    # package, so every module in it is a permitted importer of
    # `_latest_snapshot` and `_org_subtree` as far as test_import_honesty.py is
    # concerned. This allowlist is the only thing holding that line, and only
    # for the modules named below.
    @pytest.mark.parametrize(
        ("module_name", "allowed_siblings"),
        [
            ("score_snapshot", {"scoring_vocabulary", "owner"}),
            ("owner", {"_latest_snapshot", "_org_subtree"}),
            ("scoring_orchestration", {"owner", "score_snapshot"}),
        ],
    )
    def test_module_imports_only_allowed_siblings(self, module_name: str, allowed_siblings: set[str]) -> None:
        module = importlib.import_module(f"a11y_health.services.{module_name}")

        assert _sibling_service_imports(module) <= allowed_siblings


class TestDecoupledImports:
    @pytest.mark.parametrize("module_name", ["org_unit", "scan_run", "app", "brand", "page_result", "rule_finding"])
    def test_resource_service_does_not_import_scoring(self, module_name: str) -> None:
        module = importlib.import_module(f"a11y_health.services.{module_name}")

        assert not _SCORING & _sibling_service_imports(module)
