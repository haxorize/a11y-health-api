from sqlalchemy import BigInteger, Enum, ForeignKey, Index, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from a11y_health.core.database import Base, enum_values
from a11y_health.models.enums import Category, FindingType, Impact


class RuleFinding(Base):
    __tablename__ = "rule_finding"
    __table_args__ = (
        Index("ix_rule_finding_page_result_id", "page_result_id"),
        Index("ix_rule_finding_wcag_criteria", "wcag_criteria", postgresql_using="gin"),
        Index("ix_rule_finding_classifications", "classifications", postgresql_using="gin"),
    )

    page_result_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("page_result.id", ondelete="CASCADE"), nullable=False
    )
    rule_id: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[FindingType] = mapped_column(
        Enum(FindingType, name="finding_type", values_callable=enum_values),
        nullable=False,
    )
    impact: Mapped[Impact] = mapped_column(
        Enum(Impact, name="impact", values_callable=enum_values),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    help: Mapped[str] = mapped_column(Text, nullable=False)
    help_url: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[Category] = mapped_column(
        Enum(Category, name="category", values_callable=enum_values),
        nullable=False,
    )
    wcag_criteria: Mapped[list[str]] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    classifications: Mapped[list[dict[str, str]]] = mapped_column(JSONB, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
