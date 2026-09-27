from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from a11y_health.core.slug import NAME_MAX_LENGTH, derive_slug


class AppCreate(BaseModel):
    name: str = Field(max_length=NAME_MAX_LENGTH)
    brand_id: int
    org_unit_id: int

    @field_validator("name")
    @classmethod
    def name_must_be_derivable(cls, name: str) -> str:
        derive_slug(name)  # raises ValueError → framework 422 (request-shape, ADR 0022)
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
