from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from a11y_health.core.database import Base, TimestampMixin
from a11y_health.core.slug import NAME_MAX_LENGTH, SLUG_MAX_LENGTH

UQ_APP_SLUG = "uq_app_slug"
CK_APP_NAME_LENGTH = "ck_app_name_length"
CK_APP_SLUG_LENGTH = "ck_app_slug_length"
FK_APP_ORG_UNIT_ID = "fk_app_org_unit_id"
FK_APP_BRAND_ID = "fk_app_brand_id"


class App(TimestampMixin, Base):
    __tablename__ = "app"
    __table_args__ = (
        CheckConstraint(f"LENGTH(name) <= {NAME_MAX_LENGTH}", name=CK_APP_NAME_LENGTH),
        CheckConstraint(f"LENGTH(slug) <= {SLUG_MAX_LENGTH}", name=CK_APP_SLUG_LENGTH),
        UniqueConstraint("slug", name=UQ_APP_SLUG),
        Index("ix_app_org_unit_id", "org_unit_id"),
        Index("ix_app_brand_id", "brand_id"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    brand_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("brand.id", ondelete="RESTRICT", name=FK_APP_BRAND_ID), nullable=False
    )
    org_unit_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("org_unit.id", ondelete="RESTRICT", name=FK_APP_ORG_UNIT_ID), nullable=False
    )
