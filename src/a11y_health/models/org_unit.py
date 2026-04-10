from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Text
from sqlalchemy.orm import Mapped, mapped_column

from a11y_health.core.database import Base, TimestampMixin


class OrgUnit(TimestampMixin, Base):
    __tablename__ = "org_unit"
    __table_args__ = (
        CheckConstraint("LENGTH(name) <= 255", name="ck_org_unit_name_length"),
        Index("ix_org_unit_parent_id", "parent_id"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("org_unit.id", ondelete="RESTRICT"), nullable=True
    )
