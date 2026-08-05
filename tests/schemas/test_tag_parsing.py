import pytest

from a11y_health.models.enums import Category
from a11y_health.schemas._tag_parsing import extract_category, extract_wcag_criteria


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
