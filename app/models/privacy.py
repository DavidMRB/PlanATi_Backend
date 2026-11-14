from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

CONSENT_DOCUMENTS = {"PRIVACY_POLICY", "TERMS"}  # las normas de la comunidad forman parte de los términos
CONSENT_CHANNELS = {"WEB_REGISTER", "GOOGLE_COMPLETE_PROFILE", "RESTAURANT_REGISTER", "RE_ACCEPTANCE"}


class Consent(Base):
    """Prueba de la autorización del titular (Ley 1581 de 2012, Decreto 1377 de 2013).

    Historial: una fila por documento y aceptación; nunca se edita. Al eliminar la cuenta las filas
    se conservan ligadas a la lápida anonimizada, sin IP ni user agent.
    """

    __tablename__ = "consents"
    __table_args__ = (Index("ix_consents_user_accepted", "user_id", "accepted_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    document: Mapped[str] = mapped_column(String(30), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)
