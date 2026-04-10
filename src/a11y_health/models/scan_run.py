import enum
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from a11y_health.core.database import Base, TimestampMixin


class ScanRunStatus(enum.Enum):
    PENDING = "pending"
    COMPLETED = "completed"


class ScanRun(TimestampMixin, Base):
    __tablename__ = "scan_run"
    __table_args__ = (Index("ix_scan_run_app_id", "app_id"),)

    app_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("app.id", ondelete="RESTRICT"), nullable=False)
    status: Mapped[ScanRunStatus] = mapped_column(
        Enum(ScanRunStatus, name="scan_run_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
