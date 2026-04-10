"""Drop redundant scan_run_id index on score_snapshot

Revision ID: 632bbe98aa6a
Revises: 0d4a7d325fe1
Create Date: 2026-04-10 16:20:42.881837

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "632bbe98aa6a"
down_revision: str | Sequence[str] | None = "0d4a7d325fe1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index("ix_score_snapshot_scan_run_id", table_name="score_snapshot")


def downgrade() -> None:
    """Downgrade schema."""
    op.create_index("ix_score_snapshot_scan_run_id", "score_snapshot", ["scan_run_id"], unique=False)
