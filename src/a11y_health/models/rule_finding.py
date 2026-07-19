import logging
from typing import Any

from pydantic import ValidationError
from sqlalchemy import BigInteger, Enum, ForeignKey, Index, Text, TypeDecorator, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Mapped, mapped_column

from a11y_health.core.database import Base, enum_values
from a11y_health.models.classification import Classification
from a11y_health.models.enums import Category, FindingType, Impact

logger = logging.getLogger(__name__)


class _CompactClassifications(TypeDecorator[list[dict[str, str]]]):
    """The compact canonical Classification shape (ADR 0031) as a column
    guarantee: every bound value — a writer's column value or the filter's
    containment target — must validate as a Classification, and a stored entry
    written past the guard (raw-SQL backfill) is dropped from reads with a
    warning instead of failing the page that renders it."""

    impl = JSONB
    cache_ok = True

    def process_bind_param(self, value: list[Any] | None, dialect: Dialect) -> list[dict[str, str]] | None:
        if value is None:
            return None
        return [Classification.model_validate(entry).stored() for entry in value]

    def process_result_value(self, value: list[Any] | None, dialect: Dialect) -> list[dict[str, str]] | None:
        if value is None:
            return None
        kept = []
        for entry in value:
            try:
                classification = Classification.model_validate(entry)
            except ValidationError:
                logger.warning("Dropping out-of-vocabulary classification %r from a rule_finding read", entry)
                continue
            # Re-dump, don't pass through: a raw-SQL entry can validate yet
            # carry null members or extra keys the compact shape excludes.
            kept.append(classification.stored())
        return kept


class RuleFinding(Base):
    __tablename__ = "rule_finding"
    __table_args__ = (
        Index("ix_rule_finding_page_result_id_type", "page_result_id", "type"),
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
    classifications: Mapped[list[dict[str, str]]] = mapped_column(_CompactClassifications, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
