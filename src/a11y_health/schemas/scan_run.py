from datetime import datetime

from pydantic import BaseModel, ConfigDict

from a11y_health.models.enums import ScanRunStatus
from a11y_health.schemas.score_snapshot import ScoreAggregatesRead


class ScanRunCreate(BaseModel):
    scanned_at: datetime


class ScanRunStatusUpdate(BaseModel):
    status: ScanRunStatus


# The Scan Run Summary (DOMAIN.md) is a Scan Run's Score Aggregates, so a new
# field belongs on `ScoreAggregatesRead`. The empty subclass is deliberate: it
# keeps the summary a named schema of its own in openapi.json.
class ScanRunSummaryRead(ScoreAggregatesRead):
    pass


class ScanRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    app_id: int
    status: ScanRunStatus
    scanned_at: datetime
    created_at: datetime
    updated_at: datetime
