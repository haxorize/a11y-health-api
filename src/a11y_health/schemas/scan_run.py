from datetime import datetime

from pydantic import BaseModel, ConfigDict

from a11y_health.models.scan_run import ScanRunStatus

__all__ = ["ScanRunCreate", "ScanRunRead", "ScanRunStatusUpdate", "ScanRunSummaryRead"]


class ScanRunCreate(BaseModel):
    scanned_at: datetime


class ScanRunStatusUpdate(BaseModel):
    status: ScanRunStatus


class ScanRunSummaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    score: float
    total_issues: int
    pages_with_issues: int
    pages_with_critical_issues: int
    total_pages: int
    avg_issues_per_page: float
    pct_pages_with_issues: float
    pct_pages_with_critical_issues: float


class ScanRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    app_id: int
    status: ScanRunStatus
    scanned_at: datetime
    created_at: datetime
    updated_at: datetime
