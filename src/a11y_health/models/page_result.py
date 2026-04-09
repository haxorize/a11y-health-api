import enum
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Identity, Index, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from a11y_health.core.database import Base


class PageHealth(enum.Enum):
    CRITICAL = "critical"
    SERIOUS = "serious"
    FAIR = "fair"
    GOOD = "good"


class PageResult(Base):
    __tablename__ = "page_result"
    __table_args__ = (Index("ix_page_result_scan_run_id", "scan_run_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("scan_run.id", ondelete="RESTRICT"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    page_health: Mapped[PageHealth | None] = mapped_column(
        Enum(PageHealth, name="page_health", values_callable=lambda e: [m.value for m in e]),
        nullable=True,
    )
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    passes_count: Mapped[int] = mapped_column(Integer, nullable=False)
    inapplicable_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
