from fastapi import APIRouter

from a11y_health.schemas.scoring_vocabulary import ScoringVocabularyRead
from a11y_health.services import _scoring_vocabulary as scoring_vocabulary

router = APIRouter(tags=["scoring-vocabulary"])


@router.get("/scoring-vocabulary")
async def get_scoring_vocabulary() -> ScoringVocabularyRead:
    return ScoringVocabularyRead(
        page_health_ordering=list(scoring_vocabulary.PAGE_HEALTH_ORDERING),
        page_health_weights=scoring_vocabulary.PAGE_HEALTH_WEIGHT,
        impact_to_page_health=scoring_vocabulary.IMPACT_TO_PAGE_HEALTH,
    )
