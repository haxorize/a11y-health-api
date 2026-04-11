from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Index, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from a11y_health.core.database import Base, TimestampMixin

UQ_SCORE_SNAPSHOT_SCAN_RUN_ID = "uq_score_snapshot_scan_run_id"


class ScoreSnapshot(TimestampMixin, Base):
    __tablename__ = "score_snapshot"
    __table_args__ = (
        UniqueConstraint("scan_run_id", name=UQ_SCORE_SNAPSHOT_SCAN_RUN_ID),
        Index("ix_score_snapshot_app_id", "app_id"),
        Index("ix_score_snapshot_org_unit_id", "org_unit_id"),
    )

    app_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app.id", ondelete="RESTRICT"), nullable=True)
    scan_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("scan_run.id", ondelete="RESTRICT"), nullable=True
    )
    org_unit_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("org_unit.id", ondelete="RESTRICT"), nullable=True
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    total_violations: Mapped[int] = mapped_column(Integer, nullable=False)
    pages_with_violations: Mapped[int] = mapped_column(Integer, nullable=False)
    pages_with_critical_violations: Mapped[int] = mapped_column(Integer, nullable=False)
    total_pages: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_violations_per_page: Mapped[float] = mapped_column(Float, nullable=False)
    pct_pages_with_violations: Mapped[float] = mapped_column(Float, nullable=False)
    pct_pages_with_critical_violations: Mapped[float] = mapped_column(Float, nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
