from datetime import datetime

from pydantic import BaseModel, ConfigDict

from a11y_health.models.page_result import PageHealth

__all__ = ["PageMetricsRead", "PageResultRead"]


class PageMetricsRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    url: str
    page_health: PageHealth | None
    issues_count: int
    critical_issues_count: int


class PageResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    scan_run_id: int
    url: str
    page_health: PageHealth | None
    passes_count: int
    inapplicable_count: int
    created_at: datetime
    updated_at: datetime
