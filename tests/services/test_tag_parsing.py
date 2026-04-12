import pytest

from a11y_health.services._tag_parsing import extract_category, extract_classifications, extract_wcag_criterion


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("wcag2a", {"standard": "wcag", "version": "2.0", "level": "A"}),
        ("wcag2aa", {"standard": "wcag", "version": "2.0", "level": "AA"}),
        ("wcag21a", {"standard": "wcag", "version": "2.1", "level": "A"}),
        ("wcag21aa", {"standard": "wcag", "version": "2.1", "level": "AA"}),
        ("wcag22a", {"standard": "wcag", "version": "2.2", "level": "A"}),
        ("wcag22aa", {"standard": "wcag", "version": "2.2", "level": "AA"}),
    ],
)
def test_classifications_wcag_version_and_level(tag: str, expected: dict[str, str]) -> None:
    assert extract_classifications([tag]) == [expected]


def test_classifications_best_practice() -> None:
    assert extract_classifications(["best-practice"]) == [{"standard": "best-practice"}]


def test_classifications_multiple_standards() -> None:
    result = extract_classifications(["wcag2a", "wcag21a", "best-practice"])
    assert len(result) == 3
    assert {"standard": "wcag", "version": "2.0", "level": "A"} in result
    assert {"standard": "wcag", "version": "2.1", "level": "A"} in result
    assert {"standard": "best-practice"} in result


def test_classifications_unrelated_tags_ignored() -> None:
    assert extract_classifications(["cat.color", "wcag143", "ACT"]) == []


def test_classifications_empty_tags() -> None:
    assert extract_classifications([]) == []


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("wcag111", "1.1.1"),
        ("wcag143", "1.4.3"),
        ("wcag1413", "1.4.13"),
    ],
)
def test_wcag_criterion_parsed(tag: str, expected: str) -> None:
    assert extract_wcag_criterion([tag]) == expected


def test_wcag_criterion_returns_first_match() -> None:
    assert extract_wcag_criterion(["wcag111", "wcag143"]) == "1.1.1"


def test_wcag_criterion_skips_non_criterion_tags() -> None:
    assert extract_wcag_criterion(["wcag2a", "cat.color", "wcag143"]) == "1.4.3"


def test_wcag_criterion_no_match_returns_none() -> None:
    assert extract_wcag_criterion(["wcag2a", "best-practice"]) is None


def test_category_simple() -> None:
    assert extract_category(["cat.color"]) == "color"


def test_category_hyphenated() -> None:
    assert extract_category(["cat.text-alternatives"]) == "text-alternatives"


def test_category_returns_first_match() -> None:
    assert extract_category(["cat.color", "cat.forms"]) == "color"


def test_category_skips_non_category_tags() -> None:
    assert extract_category(["wcag2a", "cat.structure"]) == "structure"


def test_category_no_match_returns_none() -> None:
    assert extract_category(["wcag2a", "best-practice"]) is None
