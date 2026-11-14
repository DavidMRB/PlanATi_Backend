from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

# Acciones que registra la bitácora de moderación (`moderation_service.record_moderation_action`).
MODERATION_ACTIONS = {
    "HIDE_REVIEW",
    "RESTORE_REVIEW",
    "DELETE_REVIEW",
    "BLOCK_COMMENT",
    "UNBLOCK_COMMENT",
    "BLOCK_REPLY",
    "UNBLOCK_REPLY",
    "DELETE_REPLY",
    "DELETE_REVIEW_IMAGE",
    "DELETE_ESTABLISHMENT_IMAGE",
    "HIDE_MENU_ITEM",
    "DELETE_MENU_ITEM",
    "SUSPEND_USER",
    "REACTIVATE_USER",
    "CHANGE_ROLE",
    "SUSPEND_ESTABLISHMENT",
    "REACTIVATE_ESTABLISHMENT",
    "EDIT_ESTABLISHMENT",
    "EDIT_CATALOG",
    "RESOLVE_REPORT",
    "DISMISS_REPORT",
    "NOTIFY_USER",
    # Automática (admin_id=None): el titular eliminó su cuenta (B8); `details` solo lleva conteos.
    "DELETE_ACCOUNT",
}


class ModerationAction(Base):
    """Bitácora de moderación: quién hizo qué, sobre qué destino y por qué."""

    __tablename__ = "moderation_actions"
    __table_args__ = (
        Index("ix_moderation_actions_target", "target_type", "target_id"),
        Index("ix_moderation_actions_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # None = acción automática (p. ej. ocultado por número de reportes).
    admin_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    target_type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Copia del contenido borrado o valores antes/después de una edición.
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
