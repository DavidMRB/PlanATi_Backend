"""add google and phone verification fields

Revision ID: 0004_add_google_phone_auth
Revises: 0003_create_reviews
"""

from alembic import op
import sqlalchemy as sa

revision = "0004_add_google_phone_auth"
down_revision = "0003_create_reviews"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("google_sub", sa.String(length=255), nullable=True))
    op.add_column("users", sa.Column("picture", sa.String(length=500), nullable=True))
    op.add_column("users", sa.Column("phone_number", sa.String(length=20), nullable=True))
    op.add_column(
        "users",
        sa.Column("phone_verified", sa.Boolean(), server_default=sa.true(), nullable=False),
    )
    op.add_column(
        "users",
        sa.Column("status", sa.String(length=30), server_default="ACTIVE", nullable=False),
    )
    op.create_index("ix_users_google_sub", "users", ["google_sub"], unique=True)
    op.create_index("ix_users_phone_number", "users", ["phone_number"], unique=True)
    op.create_table(
        "phone_verification_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("phone_number", sa.String(length=20), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_phone_verification_codes_user_id", "phone_verification_codes", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_phone_verification_codes_user_id", table_name="phone_verification_codes")
    op.drop_table("phone_verification_codes")
    op.drop_index("ix_users_phone_number", table_name="users")
    op.drop_index("ix_users_google_sub", table_name="users")
    op.drop_column("users", "status")
    op.drop_column("users", "phone_verified")
    op.drop_column("users", "phone_number")
    op.drop_column("users", "picture")
    op.drop_column("users", "google_sub")
