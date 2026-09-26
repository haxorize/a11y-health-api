from collections.abc import Mapping

import pytest

import a11y_health
from a11y_health.models.classification import Classification, classifications_in
from tests.import_graph import Module, source_paths_importing


@pytest.mark.parametrize(
    ("token", "expected"),
    [
        ("wcag2a", Classification(standard="wcag", version="2.0", level="A")),
        ("wcag2aa", Classification(standard="wcag", version="2.0", level="AA")),
        ("wcag2aaa", Classification(standard="wcag", version="2.0", level="AAA")),
        ("wcag21a", Classification(standard="wcag", version="2.1", level="A")),
        ("wcag21aa", Classification(standard="wcag", version="2.1", level="AA")),
        ("wcag21aaa", Classification(standard="wcag", version="2.1", level="AAA")),
        ("wcag22a", Classification(standard="wcag", version="2.2", level="A")),
        ("wcag22aa", Classification(standard="wcag", version="2.2", level="AA")),
        ("wcag22aaa", Classification(standard="wcag", version="2.2", level="AAA")),
    ],
)
def test_classifications_in_names_each_wcag_version_and_level(token: str, expected: Classification) -> None:
    assert classifications_in([token]) == [expected]


def test_classifications_in_names_best_practice() -> None:
    assert classifications_in(["best-practice"]) == [Classification(standard="best-practice")]


def test_classifications_in_keeps_every_named_standard() -> None:
    result = classifications_in(["wcag2a", "wcag21a", "best-practice"])
    assert len(result) == 3
    assert Classification(standard="wcag", version="2.0", level="A") in result
    assert Classification(standard="wcag", version="2.1", level="A") in result
    assert Classification(standard="best-practice") in result


def test_classifications_in_names_an_aaa_only_rule() -> None:
    # An AAA-only axe rule (e.g. color-contrast-enhanced: cat.color + wcag2aaa
    # + the 1.4.6 criterion) carries its AAA Classification instead of dropping
    # to [].
    assert classifications_in(["cat.color", "wcag2aaa", "wcag146"]) == [
        Classification(standard="wcag", version="2.0", level="AAA")
    ]


def test_classifications_in_drops_what_it_cannot_name() -> None:
    assert classifications_in(["cat.color", "wcag143", "ACT"]) == []


def test_classifications_in_on_no_candidates() -> None:
    assert classifications_in([]) == []


def test_the_module_has_exactly_its_four_recorded_consumers(source_edges: Mapping[Module, frozenset[str]]) -> None:
    # The module docstring and `docs/architecture.md` both state this roster,
    # and ADR 0031's amendment enumerates a different four, so no record
    # settles the count on its own. A fifth importer would falsify two pieces
    # of prose silently; this is the walk that notices.
    consumers = source_paths_importing(
        source_edges, a11y_health, lambda names: "a11y_health.models.classification" in names
    )
    assert consumers == [
        "models/rule_finding.py",
        "schemas/axe_payload.py",
        "schemas/rule_finding.py",
        "services/rule_finding.py",
    ]
