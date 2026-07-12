"""drop derived per-page metrics from score_snapshot

Revision ID: dcf6e5671519
Revises: 8fe96135b4ba
Create Date: 2026-07-12 13:42:56.523726

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "dcf6e5671519"
down_revision: str | Sequence[str] | None = "8fe96135b4ba"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# column -> (numerator, denominator) it was derived from; downgrade recomputes
# these instead of restoring values, which is lossless because the columns were
# pure derivations of counts in the same row.
_DERIVED = {
    "avg_violations_per_page": ("total_violations", "total_pages"),
    "pct_pages_with_violations": ("pages_with_violations", "total_pages"),
    "pct_pages_with_critical_violations": ("pages_with_critical_violations", "total_pages"),
}


def upgrade() -> None:
    """Upgrade schema."""
    for column in _DERIVED:
        op.drop_column("score_snapshot", column)


def downgrade() -> None:
    """Downgrade schema."""
    # Backfill all three in one UPDATE and validate NOT NULL in one ALTER —
    # one table rewrite and one validation scan instead of three of each.
    for column in _DERIVED:
        op.add_column(
            "score_snapshot",
            sa.Column(column, sa.DOUBLE_PRECISION(precision=53), autoincrement=False, nullable=True),
        )
    op.execute(
        "UPDATE score_snapshot SET "
        + ", ".join(
            f"{column} = CASE WHEN {denominator} > 0 THEN {numerator}::double precision / {denominator} ELSE 0.0 END"
            for column, (numerator, denominator) in _DERIVED.items()
        )
    )
    op.execute("ALTER TABLE score_snapshot " + ", ".join(f"ALTER COLUMN {column} SET NOT NULL" for column in _DERIVED))
