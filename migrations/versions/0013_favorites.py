"""favorites: establishments saved by users

Revision ID: 0013_favorites
Revises: 0012_plans

- Tabla `favorites` (uno por usuario+local, `uq_favorites_user_establishment`); se borran en cascada
  con el usuario o el establecimiento.
"""

from alembic import op
import sqlalchemy as sa

revision = "0013_favorites"
down_revision = "0012_plans"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "favorites",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("establishment_id", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["establishment_id"], ["establishments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "establishment_id", name="uq_favorites_user_establishment"),
    )
    op.create_index("ix_favorites_user_created", "favorites", ["user_id", "created_at"])
    op.create_index("ix_favorites_establishment_id", "favorites", ["establishment_id"])


def downgrade() -> None:
    op.drop_index("ix_favorites_establishment_id", table_name="favorites")
    op.drop_index("ix_favorites_user_created", table_name="favorites")
    op.drop_table("favorites")
