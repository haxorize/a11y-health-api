"""remove legacy duplicate rollup score snapshots

One-time repair for #97: pre-#95 rollup recomputes appended duplicate Org Unit
and Brand Score Snapshots instead of skipping no-change observations. Per
rollup owner and `snapshot_at`, keep the row Latest Score Snapshot selection
would serve — its ordering is `snapshot_at DESC, id DESC`, so within one
observation time the winner is max id — and delete the rest. App-owned rows
are untouched: they are written one-per-Scan-Run and never accumulated
duplicates.
Irreversible: the deleted duplicates are not preserved.

Revision ID: b362121027a0
Revises: e8dedf017569
Create Date: 2026-07-12 20:23:08.717358

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b362121027a0"
down_revision: str | Sequence[str] | None = "e8dedf017569"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Partitioning on both owner columns as a tuple mirrors the Latest Score
    # Snapshot selection's rule: owner ids come from separate sequences and can
    # collide across owner types, so they are never coalesced.
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


def downgrade() -> None:
    raise NotImplementedError("irreversible: deleted duplicate rows are not preserved")
