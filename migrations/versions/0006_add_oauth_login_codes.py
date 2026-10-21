"""add oauth login codes

Revision ID: 0006_add_oauth_login_codes
Revises: 0005_add_user_nickname
"""

from alembic import op
import sqlalchemy as sa

revision = "0006_add_oauth_login_codes"
down_revision = "0005_add_user_nickname"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oauth_login_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_oauth_login_codes_user_id", "oauth_login_codes", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_oauth_login_codes_user_id", table_name="oauth_login_codes")
    op.drop_table("oauth_login_codes")
