from datetime import datetime

from pydantic import BaseModel, ConfigDict

from a11y_health.models.enums import ScanRunStatus
from a11y_health.schemas.score_snapshot import ScoreAggregatesRead

__all__ = ["ScanRunCreate", "ScanRunRead", "ScanRunStatusUpdate", "ScanRunSummaryRead"]


class ScanRunCreate(BaseModel):
    scanned_at: datetime


class ScanRunStatusUpdate(BaseModel):
    status: ScanRunStatus


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
