"""rename brand_type enum to brand

Revision ID: 65c2846883aa
Revises: 632bbe98aa6a
Create Date: 2026-04-10 22:01:03.393715

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "65c2846883aa"
down_revision: str | Sequence[str] | None = "632bbe98aa6a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE brand_type RENAME TO brand")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("ALTER TYPE brand RENAME TO brand_type")
