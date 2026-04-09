from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Identity, Index, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from a11y_health.core.database import Base


class OrgUnit(Base):
    __tablename__ = "org_unit"
    __table_args__ = (
        CheckConstraint("LENGTH(name) <= 255", name="ck_org_unit_name_length"),
        Index("ix_org_unit_parent_id", "parent_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("org_unit.id", ondelete="RESTRICT"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
