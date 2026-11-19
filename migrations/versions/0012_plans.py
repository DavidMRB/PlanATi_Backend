"""plans: scheduled visits with menu items and in-app reminders

Revision ID: 0012_plans
Revises: 0011_moderation

- Tabla `plans` (fecha en UTC, personas, recordatorio, total calculado en el servidor).
- Tabla `plan_items` con nombre y precio congelados; `menu_item_id` queda en NULL si el local borra
  el producto.
"""

from alembic import op
import sqlalchemy as sa

revision = "0012_plans"
down_revision = "0011_moderation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "plans",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("establishment_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("party_size", sa.Integer(), server_default="1", nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="SCHEDULED", nullable=False),
        sa.Column("reminder_minutes_before", sa.Integer(), nullable=True),
        sa.Column("reminder_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_amount", sa.Numeric(precision=12, scale=2), server_default="0", nullable=False),
        sa.Column("currency", sa.String(length=3), server_default="COP", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["establishment_id"], ["establishments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plans_user_scheduled", "plans", ["user_id", "scheduled_at"])
    op.create_index("ix_plans_reminder_due", "plans", ["status", "reminder_at", "reminder_sent_at"])
    op.create_index("ix_plans_establishment_status", "plans", ["establishment_id", "status"])

    op.create_table(
        "plan_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("plan_id", sa.Integer(), nullable=False),
        sa.Column("menu_item_id", sa.Integer(), nullable=True),
        sa.Column("name_snapshot", sa.String(length=120), nullable=False),
        sa.Column("unit_price_snapshot", sa.Numeric(precision=10, scale=2), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("notes", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["menu_item_id"], ["menu_items.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plan_items_plan_id", "plan_items", ["plan_id"])


def downgrade() -> None:
    op.drop_index("ix_plan_items_plan_id", table_name="plan_items")
    op.drop_table("plan_items")
    op.drop_index("ix_plans_establishment_status", table_name="plans")
    op.drop_index("ix_plans_reminder_due", table_name="plans")
    op.drop_index("ix_plans_user_scheduled", table_name="plans")
    op.drop_table("plans")
