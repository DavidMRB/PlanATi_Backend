"""moderation: account and establishment suspension, reports and moderation log

Revision ID: 0011_moderation
Revises: 0010_reviews_rating

- `suspension_reason` y `suspended_at` en `users` (nuevo estado `SUSPENDED`).
- `suspension_reason` en `establishments` (nuevo estado `SUSPENDED`, distinto de `REJECTED`).
- Tablas `reports` (reportes de usuarios, destino polimórfico) y `moderation_actions` (bitácora).

Los estados son texto libre (sin CHECK), así que `SUSPENDED` no requiere cambiar columnas.
"""

from alembic import op
import sqlalchemy as sa

revision = "0011_moderation"
down_revision = "0010_reviews_rating"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("suspension_reason", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("suspended_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("establishments", sa.Column("suspension_reason", sa.Text(), nullable=True))

    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reporter_id", sa.Integer(), nullable=False),
        sa.Column("target_type", sa.String(length=30), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=30), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=20), server_default="OPEN", nullable=False),
        sa.Column("resolved_by_id", sa.Integer(), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["reporter_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resolved_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("reporter_id", "target_type", "target_id", name="uq_reports_reporter_target"),
    )
    op.create_index("ix_reports_status_target", "reports", ["status", "target_type", "target_id"])
    op.create_index("ix_reports_reporter_id", "reports", ["reporter_id"])

    op.create_table(
        "moderation_actions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("admin_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=40), nullable=False),
        sa.Column("target_type", sa.String(length=30), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["admin_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_moderation_actions_target", "moderation_actions", ["target_type", "target_id"])
    op.create_index("ix_moderation_actions_created", "moderation_actions", ["created_at"])
    op.create_index("ix_moderation_actions_admin_id", "moderation_actions", ["admin_id"])


def downgrade() -> None:
    # Las cuentas y locales suspendidos no tienen equivalente previo: se reactivan (los locales vuelven a
    # APPROVED y las cuentas a ACTIVE o PENDING_PHONE) para no dejar estados desconocidos.
    op.execute("UPDATE establishments SET status = 'APPROVED' WHERE status = 'SUSPENDED'")
    op.execute(
        "UPDATE users SET status = CASE WHEN phone_verified THEN 'ACTIVE' ELSE 'PENDING_PHONE' END "
        "WHERE status = 'SUSPENDED'"
    )
    op.drop_index("ix_moderation_actions_admin_id", table_name="moderation_actions")
    op.drop_index("ix_moderation_actions_created", table_name="moderation_actions")
    op.drop_index("ix_moderation_actions_target", table_name="moderation_actions")
    op.drop_table("moderation_actions")
    op.drop_index("ix_reports_reporter_id", table_name="reports")
    op.drop_index("ix_reports_status_target", table_name="reports")
    op.drop_table("reports")
    op.drop_column("establishments", "suspension_reason")
    op.drop_column("users", "suspended_at")
    op.drop_column("users", "suspension_reason")
