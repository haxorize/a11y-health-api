"""Import edges that must not exist between packages under `src/`. One row per
edge: every module under the importer package is read, and any import naming
the target or a module under it is a forbidden edge.

The onboarding CLI drives the public API over HTTP with no direct database
access (README.md, "CLI"), so no CLI module imports the session layer or the
services behind the endpoints. The rows hold direct imports only: importing
the CLI still loads `core.database` transitively, through `models.enums` and
`models/__init__`, and nothing here checks that path.
"""

from collections.abc import Mapping

import pytest

from tests.import_graph import Module, synthetic_edges

_FORBIDDEN_EDGES = [
    ("a11y_health.cli", "a11y_health.core.database"),
    ("a11y_health.cli", "a11y_health.services"),
]


def _forbidden_imports(edges: Mapping[Module, frozenset[str]], importer: str, target: str) -> list[str]:
    return sorted(
        module.name
        for module, imports in edges.items()
        if module.name == importer or module.name.startswith(f"{importer}.")
        if any(name == target or name.startswith(f"{target}.") for name in imports)
    )


class TestForbiddenEdgeDetection:
    @pytest.mark.parametrize(
        "source",
        [
            "from a11y_health.services import owner\n",
            "from a11y_health import services\n",
            "import a11y_health.services.owner\n",
            "from ..services.owner import rollup\n",
        ],
        ids=["from-package", "from-root", "import", "relative"],
    )
    def test_each_spelling_of_the_edge_is_detected(self, source: str) -> None:
        edges = synthetic_edges(
            {"a11y_health.cli": "", "a11y_health.cli._ops": source, "a11y_health.services.owner": ""}
        )

        assert _forbidden_imports(edges, "a11y_health.cli", "a11y_health.services") == ["a11y_health.cli._ops"]

    def test_a_name_that_only_shares_the_prefix_is_not_the_target(self) -> None:
        edges = synthetic_edges({"a11y_health.cli": "from a11y_health.services_client import x\n"})

        assert _forbidden_imports(edges, "a11y_health.cli", "a11y_health.services") == []


@pytest.mark.parametrize(("importer", "target"), _FORBIDDEN_EDGES)
def test_forbidden_edge_is_absent(importer: str, target: str, source_edges: Mapping[Module, frozenset[str]]) -> None:
    assert any(module.name.startswith(f"{importer}.") for module in source_edges), f"no modules found under {importer}"

    assert _forbidden_imports(source_edges, importer, target) == []
