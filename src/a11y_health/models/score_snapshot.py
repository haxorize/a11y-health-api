from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType

from sqlalchemy import BigInteger, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, UniqueConstraint, text
from sqlalchemy.orm import InstrumentedAttribute, Mapped, mapped_column

from a11y_health.core.database import Base, TimestampMixin
from a11y_health.models.enums import ScoreSnapshotOwnerType

UQ_SCORE_SNAPSHOT_SCAN_RUN_ID = "uq_score_snapshot_scan_run_id"
UQ_SCORE_SNAPSHOT_ORG_UNIT_SNAPSHOT_AT = "uq_score_snapshot_org_unit_snapshot_at"
UQ_SCORE_SNAPSHOT_BRAND_SNAPSHOT_AT = "uq_score_snapshot_brand_snapshot_at"
CK_SCORE_SNAPSHOT_OWNER = "ck_score_snapshot_owner"
FK_SCORE_SNAPSHOT_ORG_UNIT_ID = "fk_score_snapshot_org_unit_id"
FK_SCORE_SNAPSHOT_BRAND_ID = "fk_score_snapshot_brand_id"


class ScoreSnapshot(TimestampMixin, Base):
    __tablename__ = "score_snapshot"
    __table_args__ = (
        UniqueConstraint("scan_run_id", name=UQ_SCORE_SNAPSHOT_SCAN_RUN_ID),
        CheckConstraint(
            "(app_id IS NOT NULL AND org_unit_id IS NULL AND brand_id IS NULL) OR "
            "(app_id IS NULL AND org_unit_id IS NOT NULL AND brand_id IS NULL) OR "
            "(app_id IS NULL AND org_unit_id IS NULL AND brand_id IS NOT NULL)",
            name=CK_SCORE_SNAPSHOT_OWNER,
        ),
        # One rollup snapshot per owner and observation time — the backstop that
        # decides rollup write races; see ADR 0015 (#98). Also the owner FK
        # lookup indexes: equality on the leading column implies the predicate.
        Index(
            UQ_SCORE_SNAPSHOT_ORG_UNIT_SNAPSHOT_AT,
            "org_unit_id",
            "snapshot_at",
            unique=True,
            postgresql_where=text("org_unit_id IS NOT NULL"),
        ),
        Index(
            UQ_SCORE_SNAPSHOT_BRAND_SNAPSHOT_AT,
            "brand_id",
            "snapshot_at",
            unique=True,
            postgresql_where=text("brand_id IS NOT NULL"),
        ),
        Index("ix_score_snapshot_app_id", "app_id"),
    )

    app_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("app.id", ondelete="CASCADE"), nullable=True)
    scan_run_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("scan_run.id", ondelete="CASCADE"), nullable=True
    )
    org_unit_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("org_unit.id", ondelete="RESTRICT", name=FK_SCORE_SNAPSHOT_ORG_UNIT_ID), nullable=True
    )
    brand_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("brand.id", ondelete="RESTRICT", name=FK_SCORE_SNAPSHOT_BRAND_ID), nullable=True
    )
    score: Mapped[float] = mapped_column(Float, nullable=False)
    total_violations: Mapped[int] = mapped_column(Integer, nullable=False)
    pages_with_violations: Mapped[int] = mapped_column(Integer, nullable=False)
    pages_with_critical_violations: Mapped[int] = mapped_column(Integer, nullable=False)
    total_pages: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


# The one owner-kind → owner-id-column dispatch, next to the columns it names —
# services (read side and rollups) derive theirs from it rather than each
# hand-maintaining a copy.
OWNER_ID_COLUMNS: Mapping[ScoreSnapshotOwnerType, InstrumentedAttribute[int | None]] = MappingProxyType(
    {
        ScoreSnapshotOwnerType.APP: ScoreSnapshot.app_id,
        ScoreSnapshotOwnerType.ORG_UNIT: ScoreSnapshot.org_unit_id,
        ScoreSnapshotOwnerType.BRAND: ScoreSnapshot.brand_id,
    }
)
