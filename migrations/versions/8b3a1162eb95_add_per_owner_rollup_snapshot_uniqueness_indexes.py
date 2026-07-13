"""add per-owner rollup snapshot uniqueness indexes

Revision ID: 8b3a1162eb95
Revises: b362121027a0
Create Date: 2026-07-13 08:55:32.304528

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8b3a1162eb95"
down_revision: str | Sequence[str] | None = "b362121027a0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# One rollup snapshot per owner and observation time — the backstop deciding
# same-observation rollup write races; see ADR 0015 (#98). Creatable only after
# the #97 cleanup (b362121027a0), whose dedupe is re-run here first: databases
# running pre-#98 code after that cleanup still race duplicates in, and one
# would fail index creation. The old single-column owner indexes are dropped as
# subsumed: an equality lookup on the leading column implies the partial
# predicate.


def upgrade() -> None:
    # Same statement as b362121027a0: per rollup owner and snapshot_at, keep the
    # max-id row (the one Latest Score Snapshot selection serves), delete the rest.
    op.execute(
        """
        DELETE FROM score_snapshot
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       row_number() OVER (
                           PARTITION BY org_unit_id, brand_id, snapshot_at
                           ORDER BY id DESC
                       ) AS rn
                FROM score_snapshot
                WHERE org_unit_id IS NOT NULL OR brand_id IS NOT NULL
            ) ranked
            WHERE rn > 1
        )
        """
    )
    op.create_index(
        "uq_score_snapshot_brand_snapshot_at",
        "score_snapshot",
        ["brand_id", "snapshot_at"],
        unique=True,
        postgresql_where=sa.text("brand_id IS NOT NULL"),
    )
    op.create_index(
        "uq_score_snapshot_org_unit_snapshot_at",
        "score_snapshot",
        ["org_unit_id", "snapshot_at"],
        unique=True,
        postgresql_where=sa.text("org_unit_id IS NOT NULL"),
    )
    op.drop_index("ix_score_snapshot_org_unit_id", table_name="score_snapshot")
    op.drop_index("ix_score_snapshot_brand_id", table_name="score_snapshot")


def downgrade() -> None:
    op.create_index("ix_score_snapshot_brand_id", "score_snapshot", ["brand_id"])
    op.create_index("ix_score_snapshot_org_unit_id", "score_snapshot", ["org_unit_id"])
    op.drop_index("uq_score_snapshot_org_unit_snapshot_at", table_name="score_snapshot")
    op.drop_index("uq_score_snapshot_brand_snapshot_at", table_name="score_snapshot")
