from collections import Counter

from a11y_health.models.enums import Impact, PageHealth
from a11y_health.services import scoring_vocabulary


def test_rank_is_position_in_worst_to_best_ordering() -> None:
    assert scoring_vocabulary.PAGE_HEALTH_RANK == {
        PageHealth.CRITICAL: 0,
        PageHealth.SERIOUS: 1,
        PageHealth.FAIR: 2,
        PageHealth.GOOD: 3,
    }


# The expected values are DOMAIN.md's ("Scoring & Metrics"), hand-written: the
# weights and the mapping decide every Score, and this is their seam (ADR
# 0021). Red when a weight or a mapping entry changes.
def test_weights_are_the_domain_values() -> None:
    assert scoring_vocabulary.PAGE_HEALTH_WEIGHT == {
        PageHealth.CRITICAL: 0.0,
        PageHealth.SERIOUS: 0.4,
        PageHealth.FAIR: 0.8,
        PageHealth.GOOD: 1.0,
    }


def test_impact_mapping_is_the_domain_mapping() -> None:
    assert scoring_vocabulary.IMPACT_TO_PAGE_HEALTH == {
        Impact.CRITICAL: PageHealth.CRITICAL,
        Impact.SERIOUS: PageHealth.SERIOUS,
        Impact.MODERATE: PageHealth.FAIR,
        Impact.MINOR: PageHealth.GOOD,
    }


class TestVocabularyCompleteness:
    def test_impact_mapping_is_total(self) -> None:
        assert set(scoring_vocabulary.IMPACT_TO_PAGE_HEALTH) == set(Impact)

    def test_every_page_health_has_a_weight(self) -> None:
        assert set(scoring_vocabulary.PAGE_HEALTH_WEIGHT) == set(PageHealth)

    def test_every_page_health_appears_exactly_once_in_ordering(self) -> None:
        assert Counter(scoring_vocabulary.PAGE_HEALTH_ORDERING) == Counter(PageHealth)
