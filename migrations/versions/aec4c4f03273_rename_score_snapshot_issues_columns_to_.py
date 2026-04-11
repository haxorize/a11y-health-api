"""rename score_snapshot issues columns to violations

Revision ID: aec4c4f03273
Revises: 65c2846883aa
Create Date: 2026-04-11 11:30:23.155378

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "aec4c4f03273"
down_revision: str | Sequence[str] | None = "65c2846883aa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RENAMES = [
    ("total_issues", "total_violations"),
    ("pages_with_issues", "pages_with_violations"),
    ("pages_with_critical_issues", "pages_with_critical_violations"),
    ("avg_issues_per_page", "avg_violations_per_page"),
    ("pct_pages_with_issues", "pct_pages_with_violations"),
    ("pct_pages_with_critical_issues", "pct_pages_with_critical_violations"),
]


def upgrade() -> None:
    """Upgrade schema."""
    for old, new in _RENAMES:
        op.alter_column("score_snapshot", old, new_column_name=new)


def downgrade() -> None:
    """Downgrade schema."""
    for old, new in _RENAMES:
        op.alter_column("score_snapshot", new, new_column_name=old)
