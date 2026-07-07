import pytest

from a11y_health.models.enums import Category
from a11y_health.schemas._tag_parsing import (
    extract_category,
    extract_classifications,
    extract_wcag_criteria,
)


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("wcag2a", {"standard": "wcag", "version": "2.0", "level": "A"}),
        ("wcag2aa", {"standard": "wcag", "version": "2.0", "level": "AA"}),
        ("wcag2aaa", {"standard": "wcag", "version": "2.0", "level": "AAA"}),
        ("wcag21a", {"standard": "wcag", "version": "2.1", "level": "A"}),
        ("wcag21aa", {"standard": "wcag", "version": "2.1", "level": "AA"}),
        ("wcag21aaa", {"standard": "wcag", "version": "2.1", "level": "AAA"}),
        ("wcag22a", {"standard": "wcag", "version": "2.2", "level": "A"}),
        ("wcag22aa", {"standard": "wcag", "version": "2.2", "level": "AA"}),
        ("wcag22aaa", {"standard": "wcag", "version": "2.2", "level": "AAA"}),
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


def test_classifications_aaa_only_rule() -> None:
    # An AAA-only axe rule (e.g. color-contrast-enhanced: cat.color + wcag2aaa +
    # the 1.4.6 criterion) carries its AAA Classification instead of dropping to [].
    assert extract_classifications(["cat.color", "wcag2aaa", "wcag146"]) == [
        {"standard": "wcag", "version": "2.0", "level": "AAA"}
    ]


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
def test_wcag_criteria_single_tag(tag: str, expected: str) -> None:
    assert extract_wcag_criteria([tag]) == [expected]


def test_wcag_criteria_returns_all_matches() -> None:
    assert extract_wcag_criteria(["wcag111", "wcag143"]) == ["1.1.1", "1.4.3"]


def test_wcag_criteria_skips_non_criterion_tags() -> None:
    assert extract_wcag_criteria(["wcag2a", "cat.color", "wcag143"]) == ["1.4.3"]


def test_wcag_criteria_empty_list_when_no_matches() -> None:
    assert extract_wcag_criteria(["wcag2a", "best-practice", "cat.color"]) == []


def test_category_simple() -> None:
    assert extract_category(["cat.color"]) == Category.COLOR


def test_category_hyphenated() -> None:
    assert extract_category(["cat.text-alternatives"]) == Category.TEXT_ALTERNATIVES


def test_category_returns_first_match() -> None:
    assert extract_category(["cat.color", "cat.forms"]) == Category.COLOR


def test_category_skips_non_category_tags() -> None:
    assert extract_category(["wcag2a", "cat.structure"]) == Category.STRUCTURE


def test_category_no_match_raises() -> None:
    with pytest.raises(ValueError, match="No category tag found"):
        extract_category(["wcag2a", "best-practice"])


def test_category_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown category: bogus"):
        extract_category(["cat.bogus"])
