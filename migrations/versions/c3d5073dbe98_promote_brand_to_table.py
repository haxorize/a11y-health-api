"""promote brand to table

Revision ID: c3d5073dbe98
Revises: aec4c4f03273
Create Date: 2026-04-11 20:44:50.719296

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c3d5073dbe98"
down_revision: str | Sequence[str] | None = "aec4c4f03273"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SEED_BRANDS = ["Humana", "CenterWell", "Go365", "CarePlus", "Reliance"]


def upgrade() -> None:
    """Upgrade schema."""
    # Temporarily rename the enum type so it doesn't conflict with the table name
    op.execute(sa.text("ALTER TYPE brand RENAME TO brand_old"))

    brand_table = op.create_table(
        "brand",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("id", sa.BigInteger(), sa.Identity(always=True), nullable=False),
        sa.CheckConstraint("LENGTH(name) <= 255", name="ck_brand_name_length"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_brand_name"),
    )

    op.bulk_insert(brand_table, [{"name": name} for name in SEED_BRANDS])

    op.add_column("app", sa.Column("brand_id", sa.BigInteger(), nullable=True))

    op.execute(sa.text("UPDATE app SET brand_id = b.id FROM brand b WHERE app.brand::text = b.name"))

    op.alter_column("app", "brand_id", nullable=False)
    op.create_index("ix_app_brand_id", "app", ["brand_id"], unique=False)
    op.create_foreign_key("fk_app_brand_id", "app", "brand", ["brand_id"], ["id"], ondelete="RESTRICT")

    op.drop_column("app", "brand")
    op.execute(sa.text("DROP TYPE IF EXISTS brand_old"))


def downgrade() -> None:
    """Downgrade schema."""
    # Temporarily rename the brand table so we can create the enum type with the same name
    op.execute(sa.text("ALTER TABLE brand RENAME TO brand_tmp"))

    brand_enum = postgresql.ENUM(*SEED_BRANDS, name="brand", create_type=True)
    brand_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "app",
        sa.Column("brand", brand_enum, nullable=True),
    )

    op.execute(sa.text("UPDATE app SET brand = b.name::brand FROM brand_tmp b WHERE app.brand_id = b.id"))

    op.alter_column("app", "brand", nullable=False)
    op.drop_constraint("fk_app_brand_id", "app", type_="foreignkey")
    op.drop_index("ix_app_brand_id", table_name="app")
    op.drop_column("app", "brand_id")
    op.execute(sa.text("DROP TABLE brand_tmp"))
