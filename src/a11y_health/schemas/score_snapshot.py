from datetime import datetime

from pydantic import BaseModel, ConfigDict

__all__ = ["ScoreMetrics", "ScoreSnapshotRead"]


class ScoreMetrics(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    score: float
    total_violations: int
    pages_with_violations: int
    pages_with_critical_violations: int
    total_pages: int
    avg_violations_per_page: float
    pct_pages_with_violations: float
    pct_pages_with_critical_violations: float


class ScoreSnapshotRead(ScoreMetrics):
    id: int
    app_id: int | None
    scan_run_id: int | None
    org_unit_id: int | None
    snapshot_at: datetime
    created_at: datetime
    updated_at: datetime
