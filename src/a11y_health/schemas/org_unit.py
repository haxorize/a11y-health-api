from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["OrgUnitCreate", "OrgUnitRead", "OrgUnitUpdate"]


class OrgUnitCreate(BaseModel):
    name: str = Field(max_length=255)
    parent_id: int | None = None


class OrgUnitUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    parent_id: int | None = Field(default=None, description="Omit to leave unchanged; send null to make a root node")


class OrgUnitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    parent_id: int | None
    created_at: datetime
    updated_at: datetime
