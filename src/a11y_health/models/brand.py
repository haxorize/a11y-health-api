from sqlalchemy import CheckConstraint, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from a11y_health.core.database import Base, TimestampMixin
from a11y_health.core.slug import NAME_MAX_LENGTH

UQ_BRAND_NAME = "uq_brand_name"
CK_BRAND_NAME_LENGTH = "ck_brand_name_length"


class Brand(TimestampMixin, Base):
    __tablename__ = "brand"
    __table_args__ = (
        CheckConstraint(f"LENGTH(name) <= {NAME_MAX_LENGTH}", name=CK_BRAND_NAME_LENGTH),
        UniqueConstraint("name", name=UQ_BRAND_NAME),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
