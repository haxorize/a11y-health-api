"""Sibling-import rules: inside one package, which modules may import which of
their siblings. Two classes enforce them — an allowlist of the siblings each
scoring module or shared helper may reach, and a decoupling pin that every
resource service imports nothing from scoring directly — and every module in
the package is in one of the two. The services layer is the only package
with such rules today; the next sibling-import rule lands here, and nothing
else does. The repo-wide private-module rule is the sibling
`test_import_honesty.py` (ADR 0038); the rules here are motivated in
architecture.md, "The Existence Guard and the two-tier call rule".
"""

import ast
import functools

import pytest

import a11y_health
from tests.import_graph import Module, package_edges

_PACKAGE = "a11y_health.services"
_SCORING = {"owner", "score_snapshot"}

# Every module under the services package sits in exactly one of these, and
# `test_every_service_module_is_classified` derives the package's membership
# rather than trusting either table to be complete.
_ALLOWED_SIBLINGS = {
    "score_snapshot": {"scoring_vocabulary", "owner"},
    "owner": {"_latest_snapshot", "_org_subtree"},
    "scoring_orchestration": {"owner", "score_snapshot"},
    # The shared helpers sit under every service, so one reaching back into a
    # sibling would close a cycle (`owner` imports `_latest_snapshot`).
    "_latest_snapshot": set(),
    "_org_subtree": set(),
    "scoring_vocabulary": set(),
}
_DECOUPLED = {"org_unit", "scan_run", "app", "brand", "page_result", "rule_finding"}


@functools.cache
def _service_edges() -> dict[str, tuple[Module, frozenset[str]]]:
    # Keyed by the name under the package; `test_name_collisions_are_reported`
    # keeps two files from sharing one.
    return {
        module.name.removeprefix(f"{_PACKAGE}."): (module, imports)
        for module, imports in package_edges(a11y_health).items()
        if module.name.startswith(f"{_PACKAGE}.")
    }


def _sibling_service_imports(module_name: str) -> set[str]:
    # The shared walk resolves every spelling, relative ones included, to
    # absolute names; this rule keeps the ones under the services package and
    # reads the sibling off each. A bare package import — `import
    # a11y_health.services` or `from a11y_health import services` — would
    # reach a sibling by attribute where no name for the filter to see, so it
    # is refused outright rather than filtered. The walk reports the bare
    # `from` form as the root package, and only the `import` form needs the
    # syntax tree.
    module, imported = _service_edges()[module_name]
    imports_package_bare = a11y_health.__name__ in imported or any(
        isinstance(node, ast.Import) and any(alias.name == _PACKAGE for alias in node.names)
        for node in ast.walk(ast.parse(module.source))
    )
    assert not imports_package_bare, f"{module.name} imports the services package bare — name the sibling instead"
    return {name.removeprefix(f"{_PACKAGE}.").split(".")[0] for name in imported if name.startswith(f"{_PACKAGE}.")}


def test_the_filter_reads_a_known_sibling_import() -> None:
    # Every decoupling pin below asserts on an empty intersection, which
    # cannot tell "imports nothing from scoring" from "the walk or the filter
    # returned nothing" — and some resource services really import no sibling,
    # so the helper cannot refuse an empty set itself. One known import pins
    # the reading instead, on the principle `import_graph.assert_descends`
    # states for the walk.
    assert "owner" in _sibling_service_imports("score_snapshot")


def test_every_service_module_is_classified() -> None:
    # Both tables were hand-copied subsets once, which left three modules and
    # every future one outside any rule. Deriving the membership makes a new
    # module fail here until it is given a row in one table.
    services = set(_service_edges())
    assert "owner" in services, "the services walk found nothing — it is not reading the package"

    assert not _ALLOWED_SIBLINGS.keys() & _DECOUPLED
    assert sorted(services - _ALLOWED_SIBLINGS.keys() - _DECOUPLED) == []
    assert sorted((_ALLOWED_SIBLINGS.keys() | _DECOUPLED) - services) == []


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
    # concerned. This allowlist is the only thing holding that line.
    @pytest.mark.parametrize(("module_name", "allowed_siblings"), _ALLOWED_SIBLINGS.items())
    def test_module_imports_only_allowed_siblings(self, module_name: str, allowed_siblings: set[str]) -> None:
        assert _sibling_service_imports(module_name) <= allowed_siblings


class TestDecoupledImports:
    @pytest.mark.parametrize("module_name", sorted(_DECOUPLED))
    def test_resource_service_does_not_import_scoring(self, module_name: str) -> None:
        assert not _SCORING & _sibling_service_imports(module_name)
