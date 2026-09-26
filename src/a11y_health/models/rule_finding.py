import logging
from collections.abc import Iterable
from typing import Any

from pydantic import ValidationError
from sqlalchemy import BigInteger, ColumnElement, Enum, ForeignKey, Index, Text, TypeDecorator, false, or_, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Mapped, mapped_column

from a11y_health.core.database import Base, enum_values
from a11y_health.models.classification import Classification, ClassificationToken, classifications_in
from a11y_health.models.enums import Category, FindingType, Impact

logger = logging.getLogger(__name__)


class _CompactClassifications(TypeDecorator[list[Classification]]):
    """Classifications in Python, the compact canonical shape (ADR 0031) in
    JSONB: every bound value — a writer's column value or the filter's
    containment target — must validate as a Classification, and a stored entry
    written past the guard (raw-SQL backfill) is dropped from reads with a
    warning instead of failing the page that renders it."""

    impl = JSONB
    cache_ok = True

    def process_bind_param(self, value: list[Any] | None, dialect: Dialect) -> list[dict[str, str]] | None:
        if value is None:
            return None
        return [Classification.model_validate(entry).stored() for entry in value]

    def process_result_value(self, value: list[Any] | None, dialect: Dialect) -> list[Classification] | None:
        if value is None:
            return None
        kept = []
        for entry in value:
            try:
                kept.append(Classification.model_validate(entry))
            except ValidationError:
                logger.warning(
                    "Dropping invalid classification %r from a rule_finding read (findings or Filter Options)", entry
                )
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
    classifications: Mapped[list[Classification]] = mapped_column(_CompactClassifications, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSONB, nullable=False)

    # One @> per token, so the GIN index on the column serves each; the column
    # type binds each target in the compact stored shape. The false() seed
    # means an empty token list matches nothing instead of building an empty
    # OR.
    @classmethod
    def classified_as_any(cls, tokens: Iterable[ClassificationToken]) -> ColumnElement[bool]:
        return or_(false(), *(cls.classifications.contains([c]) for c in classifications_in(tokens)))
