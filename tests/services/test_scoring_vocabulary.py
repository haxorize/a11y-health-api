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


class TestVocabularyCompleteness:
    def test_impact_mapping_is_total(self) -> None:
        assert set(scoring_vocabulary.IMPACT_TO_PAGE_HEALTH) == set(Impact)

    def test_every_page_health_has_exactly_one_weight(self) -> None:
        assert set(scoring_vocabulary.PAGE_HEALTH_WEIGHT) == set(PageHealth)

    def test_every_page_health_appears_exactly_once_in_ordering(self) -> None:
        assert Counter(scoring_vocabulary.PAGE_HEALTH_ORDERING) == Counter(PageHealth)
