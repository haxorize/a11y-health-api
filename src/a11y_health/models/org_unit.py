from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from a11y_health.core.database import Base, TimestampMixin
from a11y_health.core.slug import NAME_MAX_LENGTH

CK_ORG_UNIT_NAME_LENGTH = "ck_org_unit_name_length"
UQ_ORG_UNIT_SINGLE_ROOT = "uq_org_unit_single_root"
FK_ORG_UNIT_PARENT_ID = "fk_org_unit_parent_id"


class OrgUnit(TimestampMixin, Base):
    __tablename__ = "org_unit"
    __table_args__ = (
        CheckConstraint(f"LENGTH(name) <= {NAME_MAX_LENGTH}", name=CK_ORG_UNIT_NAME_LENGTH),
        Index("ix_org_unit_parent_id", "parent_id"),
        # Single-root invariant (ADR 0026): at most one parentless row may
        # exist, so the index covers only roots and the indexed expression is
        # constant.
        Index(
            UQ_ORG_UNIT_SINGLE_ROOT,
            text("(parent_id IS NULL)"),
            unique=True,
            postgresql_where=text("parent_id IS NULL"),
        ),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("org_unit.id", ondelete="RESTRICT", name=FK_ORG_UNIT_PARENT_ID), nullable=True
    )
