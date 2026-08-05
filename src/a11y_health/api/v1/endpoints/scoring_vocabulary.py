from fastapi import APIRouter

from a11y_health.schemas.scoring_vocabulary import ScoringVocabularyRead
from a11y_health.services import scoring_vocabulary as scoring_vocabulary_service

router = APIRouter(tags=["scoring-vocabulary"])


@router.get("/scoring-vocabulary")
async def get_scoring_vocabulary() -> ScoringVocabularyRead:
    return ScoringVocabularyRead(
        page_health_ordering=list(scoring_vocabulary_service.PAGE_HEALTH_ORDERING),
        page_health_weights=scoring_vocabulary_service.PAGE_HEALTH_WEIGHT,
        impact_to_page_health=scoring_vocabulary_service.IMPACT_TO_PAGE_HEALTH,
    )
