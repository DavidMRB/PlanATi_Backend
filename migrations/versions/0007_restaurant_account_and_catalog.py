"""restaurant accounts, approval status and catalog

Revision ID: 0007_restaurant_catalog
Revises: 0006_add_oauth_login_codes
"""

from alembic import op
import sqlalchemy as sa

revision = "0007_restaurant_catalog"
down_revision = "0006_add_oauth_login_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "establishments",
        sa.Column("status", sa.String(length=30), nullable=False, server_default="PENDING"),
    )
    op.create_index("ix_establishments_status", "establishments", ["status"], unique=False)
    op.add_column("establishments", sa.Column("rejection_reason", sa.Text(), nullable=True))
    op.add_column("establishments", sa.Column("phone", sa.String(length=20), nullable=True))
    op.add_column("establishments", sa.Column("contact_email", sa.String(length=255), nullable=True))
    op.add_column("establishments", sa.Column("profile_image_url", sa.String(length=500), nullable=True))
    op.add_column("establishments", sa.Column("banner_image_url", sa.String(length=500), nullable=True))
    op.add_column("establishments", sa.Column("manager_name", sa.String(length=120), nullable=True))

    op.add_column("menu_items", sa.Column("image_url", sa.String(length=500), nullable=True))
    op.add_column(
        "menu_items", sa.Column("is_combo", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column(
        "menu_items", sa.Column("is_available", sa.Boolean(), nullable=False, server_default=sa.true())
    )
    op.add_column(
        "menu_items",
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column(
        "menu_items",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )

    op.create_table(
        "combo_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("combo_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.CheckConstraint("product_id <> combo_id", name="ck_combo_items_not_self"),
        sa.ForeignKeyConstraint(["combo_id"], ["menu_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["product_id"], ["menu_items.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_combo_items_combo_id", "combo_items", ["combo_id"])
    op.create_index("ix_combo_items_product_id", "combo_items", ["product_id"])

    op.create_table(
        "establishment_images",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("establishment_id", sa.Integer(), nullable=False),
        sa.Column("image_url", sa.String(length=500), nullable=False),
        sa.Column("image_type", sa.String(length=20), nullable=False),
        sa.Column("caption", sa.String(length=150), nullable=True),
        sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["establishment_id"], ["establishments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_establishment_images_establishment_id", "establishment_images", ["establishment_id"])


def downgrade() -> None:
    op.drop_index("ix_establishment_images_establishment_id", table_name="establishment_images")
    op.drop_table("establishment_images")
    op.drop_index("ix_combo_items_product_id", table_name="combo_items")
    op.drop_index("ix_combo_items_combo_id", table_name="combo_items")
    op.drop_table("combo_items")

    for column in ("updated_at", "created_at", "is_available", "is_combo", "image_url"):
        op.drop_column("menu_items", column)

    for column in ("manager_name", "banner_image_url", "profile_image_url", "contact_email", "phone", "rejection_reason"):
        op.drop_column("establishments", column)
    op.drop_index("ix_establishments_status", table_name="establishments")
    op.drop_column("establishments", "status")
