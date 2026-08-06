import ast
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from a11y_health.core import existence
from a11y_health.core.exceptions import NotFoundError
from a11y_health.models.app import App
from a11y_health.models.brand import Brand
from a11y_health.models.org_unit import OrgUnit
from a11y_health.models.page_result import PageResult
from a11y_health.models.rule_finding import RuleFinding
from a11y_health.models.scan_run import ScanRun
from a11y_health.models.score_snapshot import ScoreSnapshot
from tests.factories import make_app_with_org_unit, make_brand
from tests.import_graph import source_paths_importing

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
    async def test_label_selection_when_absent(self, db_session: AsyncSession, model: type, label: str) -> None:
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
        assert existence.ENTITY_LABELS == EXPECTED_LABELS

    async def test_unlabeled_model_is_rejected(self, db_session: AsyncSession) -> None:
        # The table is closed: guarding a new entity requires adding its label,
        # not silently inventing one — and the label lookup is eager, so the
        # rejection fires on the entity's first guarded call, not its first miss.
        with pytest.raises(KeyError):
            await existence.get_by_pk(db_session, PageResult, 999999)


def _constructs_or_raises_not_found(tree: ast.AST) -> bool:
    aliases = {"NotFoundError"} | {
        alias.asname
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        if alias.name == "NotFoundError" and alias.asname
    }

    def names_it(expr: ast.expr | None) -> bool:
        if isinstance(expr, ast.Call):
            expr = expr.func
        if isinstance(expr, ast.Name):
            return expr.id in aliases
        return isinstance(expr, ast.Attribute) and expr.attr == "NotFoundError"

    return any(
        names_it(node if isinstance(node, ast.Call) else node.exc)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call | ast.Raise)
    )


def _imports_existence(imports: set[str]) -> bool:
    # The shared walk offers both readings of `from a11y_health.core import
    # existence`, so a membership test covers every spelling including relative.
    # Named off the module object, so renaming it moves this pin with it rather
    # than leaving a literal that matches nothing and passes vacuously.
    return existence.__name__ in imports


class TestTwoTierCallRule:
    def test_not_found_raises_only_from_the_guard(self) -> None:
        # Constructing the error is what fixes its message text, so the pin
        # covers construction as well as raise sites — binding one to a
        # variable (or aliasing the import) before raising must not escape it.
        import a11y_health

        package_root = Path(a11y_health.__file__).parent
        offenders = sorted(
            str(path.relative_to(package_root))
            for path in package_root.rglob("*.py")
            if _constructs_or_raises_not_found(ast.parse(path.read_text()))
        )
        assert offenders == ["core/existence.py"]

    def test_services_have_no_function_local_imports(self) -> None:
        # Function-local imports in services existed only to dodge the import
        # cycles the guard removed; one reappearing means a service is reaching
        # into a sibling again instead of calling the guard. Only imports inside
        # function bodies count — an indented top-level import (TYPE_CHECKING,
        # try/except) is not that pattern.
        import a11y_health.services

        services_root = Path(a11y_health.services.__file__).parent
        offenders = sorted(
            {
                f"{path.relative_to(services_root)}:{node.lineno}"
                for path in services_root.rglob("*.py")
                for func in ast.walk(ast.parse(path.read_text()))
                if isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef)
                for node in ast.walk(func)
                if isinstance(node, ast.Import | ast.ImportFrom)
            }
        )
        assert offenders == []

    def test_endpoints_never_import_the_guard(self) -> None:
        # Tier one of the call rule: endpoints read through each service's
        # named accessor; the guard is service-layer machinery.
        import a11y_health.api

        api_root = Path(a11y_health.api.__file__).parent
        offenders = source_paths_importing(api_root, a11y_health.api.__name__, _imports_existence)
        assert offenders == []
