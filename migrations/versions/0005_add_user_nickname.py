"""add user nickname

Revision ID: 0005_add_user_nickname
Revises: 0004_add_google_phone_auth
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_add_user_nickname"
down_revision = "0004_add_google_phone_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("nickname", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "nickname")
