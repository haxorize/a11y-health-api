"""convert category to enum

Revision ID: fa1abf72d371
Revises: 4f287365ba40
Create Date: 2026-04-12 14:59:08.546704

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fa1abf72d371"
down_revision: str | Sequence[str] | None = "4f287365ba40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

category_enum = sa.Enum(
    "aria",
    "color",
    "forms",
    "keyboard",
    "language",
    "name-role-value",
    "parsing",
    "semantics",
    "sensory-and-visual-cues",
    "structure",
    "tables",
    "text-alternatives",
    "time-and-media",
    name="category",
)


def upgrade() -> None:
    """Upgrade schema."""
    category_enum.create(op.get_bind())
    op.alter_column(
        "rule_finding",
        "category",
        existing_type=sa.TEXT(),
        type_=category_enum,
        nullable=False,
        postgresql_using="category::category",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "rule_finding",
        "category",
        existing_type=category_enum,
        type_=sa.TEXT(),
        nullable=True,
    )
    category_enum.drop(op.get_bind())
