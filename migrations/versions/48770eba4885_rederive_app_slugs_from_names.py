"""rederive app slugs from names

One-time repair for ADR 0019: legacy slugs were operator-supplied or verbatim
raw axe names; re-derive every slug from its name via the shared derivation
function so `slug == derive(name)` holds for pre-existing rows too. Fails
loudly (aborting the migration) if two rows collide post-derivation or a name
derives to empty — those need a human decision, not a silent merge.
Irreversible: the pre-derivation slugs are not preserved.

Revision ID: 48770eba4885
Revises: c31f27959a81
Create Date: 2026-07-05 11:43:29.159710

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from a11y_health.core.slug import rederive_slugs

# revision identifiers, used by Alembic.
revision: str = "48770eba4885"
down_revision: str | Sequence[str] | None = "c31f27959a81"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, name, slug FROM app")).all()
    derived = rederive_slugs({row.id: row.name for row in rows})
    changing = [row.id for row in rows if derived[row.id] != row.slug]

    # Two phases so the unique constraint never sees a transient collision:
    # a row's new slug may equal another row's *current* slug even when the
    # final state is collision-free. Park changing rows on a placeholder
    # (':' can't survive derivation, so it can't collide), then assign finals.
    if changing:
        conn.execute(
            sa.text("UPDATE app SET slug = :slug WHERE id = :id"),
            [{"slug": f"{revision}:{row_id}", "id": row_id} for row_id in changing],
        )
        conn.execute(
            sa.text("UPDATE app SET slug = :slug WHERE id = :id"),
            [{"slug": derived[row_id], "id": row_id} for row_id in changing],
        )


def downgrade() -> None:
    raise NotImplementedError("irreversible: pre-derivation slugs are not preserved")
