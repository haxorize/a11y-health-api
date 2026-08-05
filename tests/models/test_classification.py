import logging

import pytest

from a11y_health.models.classification import (
    Classification,
    classification_options,
    classifications_in,
    token_to_stored_classification,
)


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
    # An AAA-only axe rule (e.g. color-contrast-enhanced: cat.color + wcag2aaa +
    # the 1.4.6 criterion) carries its AAA Classification instead of dropping to [].
    assert classifications_in(["cat.color", "wcag2aaa", "wcag146"]) == [
        Classification(standard="wcag", version="2.0", level="AAA")
    ]


def test_classifications_in_drops_what_it_cannot_name() -> None:
    assert classifications_in(["cat.color", "wcag143", "ACT"]) == []


def test_classifications_in_on_no_candidates() -> None:
    assert classifications_in([]) == []


def test_classification_options_drop_invalid_entry_with_warning(caplog: pytest.LogCaptureFixture) -> None:
    # "Callers need not pre-clean": an invalid stored entry is dropped with a
    # warning, mirroring the tolerant column read, never raised.
    with caplog.at_level(logging.WARNING):
        options = classification_options([{"standard": "section508"}, token_to_stored_classification("wcag2aa")])

    assert [token for token, _ in options] == ["wcag2aa"]
    assert "section508" in caplog.text
