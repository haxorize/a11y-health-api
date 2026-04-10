from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column

from a11y_health.core.database import Base, TimestampMixin


class ScoreSnapshot(TimestampMixin, Base):
    __tablename__ = "score_snapshot"
    __table_args__ = (
        Index("ix_score_snapshot_app_id", "app_id"),
        Index("ix_score_snapshot_scan_run_id", "scan_run_id"),
        Index("ix_score_snapshot_org_unit_id", "org_unit_id"),
    )

    app_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app.id", ondelete="RESTRICT"), nullable=True)
    scan_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("scan_run.id", ondelete="RESTRICT"), nullable=True, unique=True
    )
    org_unit_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("org_unit.id", ondelete="RESTRICT"), nullable=True
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    total_issues: Mapped[int] = mapped_column(Integer, nullable=False)
    pages_with_issues: Mapped[int] = mapped_column(Integer, nullable=False)
    pages_with_critical_issues: Mapped[int] = mapped_column(Integer, nullable=False)
    total_pages: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_issues_per_page: Mapped[float] = mapped_column(Float, nullable=False)
    pct_pages_with_issues: Mapped[float] = mapped_column(Float, nullable=False)
    pct_pages_with_critical_issues: Mapped[float] = mapped_column(Float, nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
