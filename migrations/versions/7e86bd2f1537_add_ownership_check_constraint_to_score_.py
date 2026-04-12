"""add ownership check constraint to score_snapshot

Revision ID: 7e86bd2f1537
Revises: c6db486866ba
Create Date: 2026-04-11 23:28:22.429753

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7e86bd2f1537"
down_revision: str | Sequence[str] | None = "c6db486866ba"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_check_constraint(
        "ck_score_snapshot_owner",
        "score_snapshot",
        "(app_id IS NOT NULL AND org_unit_id IS NULL AND brand_id IS NULL) OR "
        "(app_id IS NULL AND org_unit_id IS NOT NULL AND brand_id IS NULL) OR "
        "(app_id IS NULL AND org_unit_id IS NULL AND brand_id IS NOT NULL)",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("ck_score_snapshot_owner", "score_snapshot", type_="check")
