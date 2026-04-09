import enum

from sqlalchemy import BigInteger, Enum, ForeignKey, Identity, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from a11y_health.core.database import Base


class FindingType(enum.Enum):
    VIOLATION = "violation"
    INCOMPLETE = "incomplete"


class Impact(enum.Enum):
    CRITICAL = "critical"
    SERIOUS = "serious"
    MODERATE = "moderate"
    MINOR = "minor"


class RuleFinding(Base):
    __tablename__ = "rule_finding"
    __table_args__ = (Index("ix_rule_finding_page_result_id", "page_result_id"),)

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=True), primary_key=True)
    page_result_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("page_result.id", ondelete="CASCADE"), nullable=False
    )
    rule_id: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[FindingType] = mapped_column(
        Enum(FindingType, name="finding_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    impact: Mapped[Impact] = mapped_column(
        Enum(Impact, name="impact", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    help: Mapped[str] = mapped_column(Text, nullable=False)
    help_url: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text, nullable=True)
    wcag_criterion: Mapped[str | None] = mapped_column(Text, nullable=True)
    classifications: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
