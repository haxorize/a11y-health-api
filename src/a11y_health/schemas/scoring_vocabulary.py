from pydantic import BaseModel

from a11y_health.models.enums import Impact, PageHealth

__all__ = ["ScoringVocabularyRead"]


class ScoringVocabularyRead(BaseModel):
    page_health_ordering: list[PageHealth]
    page_health_weights: dict[PageHealth, float]
    impact_to_page_health: dict[Impact, PageHealth]
