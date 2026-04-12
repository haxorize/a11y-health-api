from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["AppCreate", "AppRead", "AppUpdate"]


class AppCreate(BaseModel):
    name: str = Field(max_length=255)
    slug: str = Field(max_length=255)
    brand_id: int
    org_unit_id: int


class AppUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    org_unit_id: int | None = None


class AppRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    brand_id: int
    org_unit_id: int
    created_at: datetime
    updated_at: datetime
