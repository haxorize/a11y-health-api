import enum
from typing import Any

from sqlalchemy import BigInteger, Enum, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from a11y_health.core.database import Base, TimestampMixin


class PageHealth(enum.Enum):
    CRITICAL = "critical"
    SERIOUS = "serious"
    FAIR = "fair"
    GOOD = "good"


class PageResult(TimestampMixin, Base):
    __tablename__ = "page_result"
    __table_args__ = (Index("ix_page_result_scan_run_id", "scan_run_id"),)

    scan_run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("scan_run.id", ondelete="RESTRICT"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    page_health: Mapped[PageHealth | None] = mapped_column(
        Enum(PageHealth, name="page_health", values_callable=lambda e: [m.value for m in e]),
        nullable=True,
    )
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    passes_count: Mapped[int] = mapped_column(Integer, nullable=False)
    inapplicable_count: Mapped[int] = mapped_column(Integer, nullable=False)
