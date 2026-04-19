"""seed org unit humana

Revision ID: 3737c72ff7ef
Revises: fa1abf72d371
Create Date: 2026-04-12 19:50:36.308621

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3737c72ff7ef"
down_revision: str | Sequence[str] | None = "fa1abf72d371"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("INSERT INTO org_unit (name) VALUES ('Humana Inc.')")


def downgrade() -> None:
    op.execute("DELETE FROM org_unit WHERE name = 'Humana Inc.'")
