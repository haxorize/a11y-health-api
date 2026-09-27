from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from a11y_health.core.slug import NAME_MAX_LENGTH


class OrgUnitCreate(BaseModel):
    name: str = Field(max_length=NAME_MAX_LENGTH)
    parent_id: int | None = None


class OrgUnitUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=NAME_MAX_LENGTH)
    parent_id: int | None = Field(default=None, description="Omit to leave unchanged; send null to make a root node")


class OrgUnitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    parent_id: int | None
    created_at: datetime
    updated_at: datetime
