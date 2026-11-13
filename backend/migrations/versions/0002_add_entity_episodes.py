"""Add entity.episodes (F-015).

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-13

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ANIME_ONLY = op.f("ck_entity_anime_only_fields")


def upgrade() -> None:
    op.add_column("entity", sa.Column("episodes", sa.Integer(), nullable=True))
    op.drop_constraint(ANIME_ONLY, "entity", type_="check")
    op.create_check_constraint(
        ANIME_ONLY,
        "entity",
        "(start_year IS NULL AND end_year IS NULL AND score IS NULL AND episodes IS NULL) "
        "OR kind = 'anime'",
    )


def downgrade() -> None:
    op.drop_constraint(ANIME_ONLY, "entity", type_="check")
    op.drop_column("entity", "episodes")
    op.create_check_constraint(
        ANIME_ONLY,
        "entity",
        "(start_year IS NULL AND end_year IS NULL AND score IS NULL) OR kind = 'anime'",
    )
