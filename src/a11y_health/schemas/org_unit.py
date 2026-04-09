import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["OrgUnitCreate", "OrgUnitRead", "OrgUnitUpdate"]


class OrgUnitCreate(BaseModel):
    name: str = Field(max_length=255)
    parent_id: uuid.UUID | None = None


class OrgUnitUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    parent_id: uuid.UUID | None = None


class OrgUnitRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    parent_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
