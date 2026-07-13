"""name the app org_unit_id fk constraint

Revision ID: e8dedf017569
Revises: dcf6e5671519
Create Date: 2026-07-12 20:12:25.776227

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e8dedf017569"
down_revision: str | Sequence[str] | None = "dcf6e5671519"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The Dependents Guard maps this constraint's name to has_dependents (409), so it
# must match FK_APP_ORG_UNIT_ID. RENAME is catalog-only — no revalidation, no lock
# beyond ACCESS EXCLUSIVE on the catalog row.


def upgrade() -> None:
    op.execute("ALTER TABLE app RENAME CONSTRAINT app_org_unit_id_fkey TO fk_app_org_unit_id")


def downgrade() -> None:
    op.execute("ALTER TABLE app RENAME CONSTRAINT fk_app_org_unit_id TO app_org_unit_id_fkey")
