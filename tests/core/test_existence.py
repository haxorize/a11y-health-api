import ast
from collections.abc import Mapping

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core import exceptions, existence
from a11y_health.core.exceptions import LabeledModel, NotFoundError
from a11y_health.models.app import App
from a11y_health.models.brand import Brand
from a11y_health.models.org_unit import OrgUnit
from a11y_health.models.page_result import PageResult
from a11y_health.models.rule_finding import RuleFinding
from a11y_health.models.scan_run import ScanRun
from a11y_health.models.score_snapshot import ScoreSnapshot
from tests.factories import make_app_with_org_unit, make_brand, make_page_result_with_parents
from tests.import_graph import Module, package_root, parsed, source_paths_importing

# Message text is the observable contract — each label must match the wording
# the entity services raised before the guard existed.
EXPECTED_LABELS = {
    App: "App",
    Brand: "Brand",
    OrgUnit: "Org unit",
    ScanRun: "Scan run",
    RuleFinding: "Finding",
    ScoreSnapshot: "Scan run summary",
}


class TestGetByPk:
    async def test_returns_entity_when_present(self, db_session: AsyncSession) -> None:
        brand = await make_brand(db_session)

        found = await existence.get_by_pk(db_session, Brand, brand.id)

        assert found is brand

    @pytest.mark.parametrize(("model", "label"), EXPECTED_LABELS.items())
    async def test_label_selection_when_absent(self, db_session: AsyncSession, model: LabeledModel, label: str) -> None:
        with pytest.raises(NotFoundError) as exc_info:
            await existence.get_by_pk(db_session, model, 999999)

        assert str(exc_info.value) == f"{label} 999999 not found"


class TestGetByQuery:
    async def test_returns_entity_when_present(self, db_session: AsyncSession) -> None:
        app = await make_app_with_org_unit(db_session, slug="my-app")

        found = await existence.get_by_query(db_session, App, select(App).where(App.slug == "my-app"), "my-app")

        assert found is app

    async def test_raises_not_found_when_absent(self, db_session: AsyncSession) -> None:
        stmt = select(App).where(App.slug == "no-such-app")

        with pytest.raises(NotFoundError) as exc_info:
            await existence.get_by_query(db_session, App, stmt, "no-such-app")

        assert str(exc_info.value) == "App no-such-app not found"


class TestEntityLabels:
    def test_every_guarded_entity_has_a_label(self) -> None:
        assert exceptions.ENTITY_LABELS == EXPECTED_LABELS

    # The table is closed: guarding a new entity requires adding its label,
    # not silently inventing one. The rows exist, so only the eager label
    # check can raise; a miss would raise from the error's constructor.
    async def test_unlabeled_model_is_rejected_by_pk_on_a_hit(self, db_session: AsyncSession) -> None:
        row = await make_page_result_with_parents(db_session)

        with pytest.raises(KeyError, match="PageResult"):
            await existence.get_by_pk(db_session, PageResult, row.id)  # ty: ignore[invalid-argument-type]

    async def test_unlabeled_model_is_rejected_by_query_on_a_hit(self, db_session: AsyncSession) -> None:
        row = await make_page_result_with_parents(db_session)
        stmt = select(PageResult).where(PageResult.id == row.id)

        with pytest.raises(KeyError, match="PageResult"):
            await existence.get_by_query(db_session, PageResult, stmt, row.id)  # ty: ignore[invalid-argument-type]


# Outside the guard only these are named: the private builder, or a public
# one added beside them, would let a module build the error itself. Named off
# the functions, so a rename moves the pin rather than leaving a stale literal.
_GUARD_ENTRY_POINTS = frozenset(
    entry.__name__
    for entry in (existence.get_by_pk, existence.get_by_query, existence.lock_by_pk, existence.require_reference)
)
_GUARD_LEAF = existence.__name__.rpartition(".")[2]


def _builds_not_found(tree: ast.AST) -> bool:
    error_names = {"NotFoundError"}
    guard_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            from_guard = node.module is not None and node.module.rpartition(".")[2] == _GUARD_LEAF
            for alias in node.names:
                if alias.name == "NotFoundError" and alias.asname:
                    error_names.add(alias.asname)
                elif alias.name == _GUARD_LEAF:
                    guard_names.add(alias.asname or alias.name)
                elif from_guard and alias.name not in _GUARD_ENTRY_POINTS:
                    return True
        elif isinstance(node, ast.Import):
            # Unaliased, the dotted chain below already catches it.
            guard_names.update(
                alias.asname for alias in node.names if alias.asname and alias.name.rpartition(".")[2] == _GUARD_LEAF
            )

    def names_the_error(expr: ast.expr | None) -> bool:
        if isinstance(expr, ast.Call):
            expr = expr.func
        if isinstance(expr, ast.Name):
            return expr.id in error_names
        return isinstance(expr, ast.Attribute) and expr.attr == "NotFoundError"

    def names_a_guard_builder(node: ast.AST) -> bool:
        # `import a11y_health.core.existence` reaches it as a dotted chain.
        if not isinstance(node, ast.Attribute) or node.attr in _GUARD_ENTRY_POINTS:
            return False
        owner = node.value
        return (isinstance(owner, ast.Name) and owner.id in guard_names) or (
            isinstance(owner, ast.Attribute) and owner.attr == _GUARD_LEAF
        )

    return any(
        names_a_guard_builder(node)
        or (isinstance(node, ast.Call) and names_the_error(node))
        or (isinstance(node, ast.Raise) and names_the_error(node.exc))
        for node in ast.walk(tree)
    )


def _imports_existence(imports: set[str]) -> bool:
    # The shared walk offers both readings of `from a11y_health.core import
    # existence`, so a membership test covers every spelling including relative.
    # Named off the module object, so renaming it moves this pin with it rather
    # than leaving a literal that matches nothing and passes vacuously.
    return existence.__name__ in imports


def _function_local_import_lines(tree: ast.AST) -> list[int]:
    return sorted(
        {
            node.lineno
            for func in ast.walk(tree)
            if isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef)
            for node in ast.walk(func)
            if isinstance(node, ast.Import | ast.ImportFrom)
        }
    )


class TestTwoTierCallRule:
    def test_not_found_is_built_only_by_the_guard(self, source_edges: Mapping[Module, frozenset[str]]) -> None:
        # Constructing the error is what fixes its message text, so the pin
        # covers construction, and any name reaching the guard's private
        # builder, not only raise sites. A write takes its mapping entry from
        # `require_reference` and the Integrity Guard raises that value.
        offenders = [module.name for module in source_edges if _builds_not_found(parsed(module))]
        assert offenders == [existence.__name__]

    def test_services_have_no_function_local_imports(self, source_edges: Mapping[Module, frozenset[str]]) -> None:
        # Function-local imports in services existed only to dodge the import
        # cycles the guard removed; one reappearing means a service is reaching
        # into a sibling again instead of calling the guard.
        import a11y_health.services

        services = [module for module in source_edges if module.path.is_relative_to(package_root(a11y_health.services))]
        assert services, "the services walk found nothing — it is not reading the package"
        offenders = [
            f"{module.name}:{line}" for module in services for line in _function_local_import_lines(parsed(module))
        ]
        assert offenders == []

    def test_endpoints_never_import_the_guard(self, source_edges: Mapping[Module, frozenset[str]]) -> None:
        # Tier one of the call rule: endpoints read through each service's
        # named accessor; the guard is service-layer machinery.
        import a11y_health.api

        offenders = source_paths_importing(source_edges, a11y_health.api, _imports_existence)
        assert offenders == []


_BUILDER = existence._not_found.__name__


class TestNotFoundDetection:
    # A second build site fails the walk above only if the detector sees it in
    # every spelling a service could write it in. The `not_found` cases are
    # the public builder the guard once had, and a public builder added again.
    @pytest.mark.parametrize(
        "source",
        [
            "from a11y_health.core.exceptions import NotFoundError\nraise NotFoundError(App, 1)\n",
            "from a11y_health.core import exceptions\nraise exceptions.NotFoundError(App, 1)\n",
            "from a11y_health.core.exceptions import NotFoundError as Missing\nerror = Missing(App, 1)\nraise error\n",
            "from a11y_health.core import existence\nraise existence.not_found(App, 1)\n",
            "from a11y_health.core.existence import not_found\nraise not_found(App, 1)\n",
            "from a11y_health.core import existence\ne = existence.not_found(App, 1)\n",
            f"from a11y_health.core import existence\nraise existence.{_BUILDER}(App, 1)\n",
            f"from ..core.existence import {_BUILDER} as build\nraise build(App, 1)\n",
            f"from a11y_health.core import existence as guard\ne = guard.{_BUILDER}(App, 1)\n",
            f"import a11y_health.core.existence\ne = a11y_health.core.existence.{_BUILDER}(App, 1)\n",
            f"import a11y_health.core.existence as ex\ne = ex.{_BUILDER}(App, 1)\n",
        ],
        ids=[
            "direct",
            "attribute",
            "aliased-and-bound",
            "public-builder-raised",
            "public-builder-imported",
            "public-builder-bound",
            "private-builder",
            "private-builder-relative-import",
            "private-builder-aliased-module",
            "private-builder-dotted",
            "aliased-module-import",
        ],
    )
    def test_a_second_site_is_detected(self, source: str) -> None:
        assert _builds_not_found(ast.parse(source))

    def test_a_module_that_only_catches_it_is_not_a_site(self) -> None:
        source = "try:\n    pass\nexcept NotFoundError:\n    pass\n"

        assert not _builds_not_found(ast.parse(source))

    def test_the_entry_points_and_a_mapped_raise_are_not_sites(self) -> None:
        # The Integrity Guard's raise of a mapped value is how a write's
        # not-found mode reaches the caller, so it has to stay unflagged.
        calls = "".join(f"existence.{name}(session, App, 1)\n" for name in sorted(_GUARD_ENTRY_POINTS))
        source = f"from a11y_health.core import existence\n{calls}raise constraint_errors[violated]\n"

        assert not _builds_not_found(ast.parse(source))


class TestFunctionLocalImportDetection:
    # The repo-wide assertion above is on an empty list, so the detector
    # carries its own known-bad. Narrowing its descent to a function's direct
    # children reds the nested case.
    def test_an_import_nested_inside_a_function_body_is_reported(self) -> None:
        source = (
            "def load():\n"
            "    import json\n"
            "    if True:\n"
            "        from a11y_health.services import owner\n"
            "async def fetch():\n"
            "    try:\n"
            "        import os\n"
            "    except ImportError:\n"
            "        pass\n"
        )

        assert _function_local_import_lines(ast.parse(source)) == [2, 4, 7]

    def test_an_indented_top_level_import_is_permitted(self) -> None:
        # TYPE_CHECKING and try/except blocks indent an import without putting
        # it in a function body, which is not the pattern the rule exists for.
        source = (
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from a11y_health.services import owner\n"
            "try:\n"
            "    import orjson\n"
            "except ImportError:\n"
            "    orjson = None\n"
        )

        assert _function_local_import_lines(ast.parse(source)) == []
