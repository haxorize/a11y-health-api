from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Enum,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from a11y_health.core.database import Base, TimestampMixin, enum_values
from a11y_health.models.enums import Brand

UQ_APP_SLUG = "uq_app_slug"
CK_APP_NAME_LENGTH = "ck_app_name_length"
CK_APP_SLUG_LENGTH = "ck_app_slug_length"


class App(TimestampMixin, Base):
    __tablename__ = "app"
    __table_args__ = (
        CheckConstraint("LENGTH(name) <= 255", name=CK_APP_NAME_LENGTH),
        CheckConstraint("LENGTH(slug) <= 255", name=CK_APP_SLUG_LENGTH),
        UniqueConstraint("slug", name=UQ_APP_SLUG),
        Index("ix_app_org_unit_id", "org_unit_id"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    brand: Mapped[Brand] = mapped_column(
        Enum(Brand, name="brand", values_callable=enum_values),
        nullable=False,
    )
    org_unit_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("org_unit.id", ondelete="RESTRICT"), nullable=False)
