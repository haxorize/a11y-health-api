"""name the six foreign keys and add the app snapshot probe index

Revision ID: b65e800fc49b
Revises: 8b3a1162eb95
Create Date: 2026-10-18 16:55:07.883699

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b65e800fc49b"
down_revision: str | Sequence[str] | None = "8b3a1162eb95"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Each foreign key PostgreSQL named by default, renamed to the name the models'
# naming convention gives it (ADR 0051). RENAME is catalog-only: no row is
# revalidated.
_RENAMES = (
    ("node_finding", "node_finding_rule_finding_id_fkey", "fk_node_finding_rule_finding_id"),
    ("rule_finding", "rule_finding_page_result_id_fkey", "fk_rule_finding_page_result_id"),
    ("page_result", "page_result_scan_run_id_fkey", "fk_page_result_scan_run_id"),
    ("scan_run", "scan_run_app_id_fkey", "fk_scan_run_app_id"),
    ("score_snapshot", "score_snapshot_app_id_fkey", "fk_score_snapshot_app_id"),
    ("score_snapshot", "score_snapshot_scan_run_id_fkey", "fk_score_snapshot_scan_run_id"),
)


def upgrade() -> None:
    for table, default, convention in _RENAMES:
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {default} TO {convention}")
    op.create_index(
        "ix_score_snapshot_app_id_snapshot_at_id",
        "score_snapshot",
        ["app_id", sa.literal_column("snapshot_at DESC"), sa.literal_column("id DESC")],
    )
    op.drop_index("ix_score_snapshot_app_id", table_name="score_snapshot")


def downgrade() -> None:
    op.create_index("ix_score_snapshot_app_id", "score_snapshot", ["app_id"])
    op.drop_index("ix_score_snapshot_app_id_snapshot_at_id", table_name="score_snapshot")
    for table, default, convention in _RENAMES:
        op.execute(f"ALTER TABLE {table} RENAME CONSTRAINT {convention} TO {default}")
