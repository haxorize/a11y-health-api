from typing import Any

from sqlalchemy import BigInteger, Enum, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, deferred, mapped_column

from a11y_health.core.database import Base, TimestampMixin, enum_values
from a11y_health.models.enums import PageHealth


class PageResult(TimestampMixin, Base):
    __tablename__ = "page_result"
    __table_args__ = (Index("ix_page_result_scan_run_id_id", "scan_run_id", "id"),)

    scan_run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("scan_run.id", ondelete="CASCADE"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    page_health: Mapped[PageHealth | None] = mapped_column(
        Enum(PageHealth, name="page_health", values_callable=enum_values),
        nullable=True,
    )
    raw_json: Mapped[dict[str, Any]] = deferred(mapped_column(JSONB, nullable=False))
    passes_count: Mapped[int] = mapped_column(Integer, nullable=False)
    inapplicable_count: Mapped[int] = mapped_column(Integer, nullable=False)
