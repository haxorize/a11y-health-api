from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from a11y_health.core.slug import derive_slug

__all__ = ["AppCreate", "AppRead", "AppUpdate"]


class AppCreate(BaseModel):
    name: str = Field(max_length=255)
    brand_id: int
    org_unit_id: int

    @field_validator("name")
    @classmethod
    def name_must_be_derivable(cls, name: str) -> str:
        derive_slug(name)  # raises ValueError → framework 422 (request-shape, ADR 0009)
        return name


class AppUpdate(BaseModel):
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
