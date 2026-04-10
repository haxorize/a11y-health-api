from typing import Any

from sqlalchemy import BigInteger, Enum, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, deferred, mapped_column

from a11y_health.core.database import Base, enum_values
from a11y_health.models.rule_finding import Impact


class NodeFinding(Base):
    __tablename__ = "node_finding"
    __table_args__ = (Index("ix_node_finding_rule_finding_id", "rule_finding_id"),)

    rule_finding_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("rule_finding.id", ondelete="CASCADE"), nullable=False
    )
    html: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    impact: Mapped[Impact] = mapped_column(
        Enum(Impact, name="impact", create_type=False, values_callable=enum_values),
        nullable=False,
    )
    failure_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    checks: Mapped[dict[str, Any]] = deferred(mapped_column(JSONB, nullable=False))
