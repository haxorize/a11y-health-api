from datetime import datetime

from pydantic import BaseModel, ConfigDict

__all__ = ["ScoreMetrics", "ScoreSnapshotRead"]


class ScoreMetrics(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    score: float
    total_issues: int
    pages_with_issues: int
    pages_with_critical_issues: int
    total_pages: int
    avg_issues_per_page: float
    pct_pages_with_issues: float
    pct_pages_with_critical_issues: float


class ScoreSnapshotRead(ScoreMetrics):
    id: int
    app_id: int | None
    scan_run_id: int | None
    org_unit_id: int | None
    snapshot_at: datetime
    created_at: datetime
    updated_at: datetime
