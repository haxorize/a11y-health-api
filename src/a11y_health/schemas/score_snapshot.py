from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# The wire form of Score Aggregates (DOMAIN.md): its fields are a subset of
# `services.owner.ScoreAggregates`, which a test pins — a field joining the wire
# and not the value ships a snapshot the client cannot read back.
class ScoreAggregatesRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    score: float = Field(description="A 0 to 1 fraction, not a percentage: a perfect score is 1.0.")
    total_violations: int
    pages_with_violations: int
    pages_with_critical_violations: int
    total_pages: int


class ScoreSnapshotRead(ScoreAggregatesRead):
    id: int
    app_id: int | None
    scan_run_id: int | None
    org_unit_id: int | None
    brand_id: int | None
    snapshot_at: datetime
    created_at: datetime
    updated_at: datetime
