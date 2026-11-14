from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NotificationType(StrEnum):
    REVIEW_RECEIVED = "REVIEW_RECEIVED"  # al dueño del establecimiento
    REVIEW_REPLIED = "REVIEW_REPLIED"  # al autor de la reseña
    REVIEW_PROMPT = "REVIEW_PROMPT"  # tras un plan completado: "¿Cómo te fue?"
    CONTENT_MODERATED = "CONTENT_MODERATED"  # contenido oculto, bloqueado o borrado por moderación
    CONTENT_RESTORED = "CONTENT_RESTORED"
    ACCOUNT_SUSPENDED = "ACCOUNT_SUSPENDED"
    ACCOUNT_REACTIVATED = "ACCOUNT_REACTIVATED"
    ESTABLISHMENT_APPROVED = "ESTABLISHMENT_APPROVED"
    ESTABLISHMENT_REJECTED = "ESTABLISHMENT_REJECTED"
    ESTABLISHMENT_SUSPENDED = "ESTABLISHMENT_SUSPENDED"
    ESTABLISHMENT_REACTIVATED = "ESTABLISHMENT_REACTIVATED"
    ESTABLISHMENT_EDITED_BY_ADMIN = "ESTABLISHMENT_EDITED_BY_ADMIN"
    PLAN_REMINDER = "PLAN_REMINDER"
    PLAN_AFFECTED = "PLAN_AFFECTED"  # el establecimiento del plan fue suspendido
    REPORT_RESOLVED = "REPORT_RESOLVED"  # a quien reportó
    ADMIN_REPORT_OPENED = "ADMIN_REPORT_OPENED"  # a los admins
    ADMIN_MESSAGE = "ADMIN_MESSAGE"  # aviso manual del admin


class Notification(Base):
    """Notificación dentro de la app. El frontend la consulta por polling (`/notifications/unread-count`)."""

    __tablename__ = "notifications"
    __table_args__ = (
        # También sirve como índice de `user_id` (columna líder): no hace falta otro índice aparte.
        Index("ix_notifications_user_read_created", "user_id", "read_at", "created_at"),
        UniqueConstraint("dedupe_key", name="uq_notifications_dedupe_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(150), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Ruta relativa del frontend, p. ej. "/plans/12".
    link: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Ids auxiliares (plan_id, review_id, establishment_id…).
    data: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    # Evita duplicados (p. ej. un recordatorio por plan y hora); NULL = sin restricción.
    dedupe_key: Mapped[str | None] = mapped_column(String(150), nullable=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
