"""privacy: consents, legal versions and account deletion (Ley 1581)

Revision ID: 0014_privacy
Revises: 0013_favorites

- `users`: `privacy_policy_version`, `terms_version`, `consents_updated_at` (copia de la última
  aceptación), `last_data_export_at` y `deleted_at`. Las cuentas existentes quedan sin versión
  aceptada: se les pedirá aceptar al entrar (`pending_consents`, 403 `CONSENT_REQUIRED`).
- Tabla `consents` (historial de aceptaciones con canal, IP y user agent).
- `phone_verification_codes.purpose` (`VERIFY_PHONE` | `DELETE_ACCOUNT`).
"""

from alembic import op
import sqlalchemy as sa

revision = "0014_privacy"
down_revision = "0013_favorites"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("privacy_policy_version", sa.String(20), nullable=True))
    op.add_column("users", sa.Column("terms_version", sa.String(20), nullable=True))
    op.add_column("users", sa.Column("consents_updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("last_data_export_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "phone_verification_codes",
        sa.Column("purpose", sa.String(20), server_default="VERIFY_PHONE", nullable=False),
    )
    op.create_table(
        "consents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("document", sa.String(30), nullable=False),
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(255), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_consents_user_accepted", "consents", ["user_id", "accepted_at"])


def downgrade() -> None:
    op.drop_index("ix_consents_user_accepted", table_name="consents")
    op.drop_table("consents")
    op.drop_column("phone_verification_codes", "purpose")
    op.drop_column("users", "deleted_at")
    op.drop_column("users", "last_data_export_at")
    op.drop_column("users", "consents_updated_at")
    op.drop_column("users", "terms_version")
    op.drop_column("users", "privacy_policy_version")
