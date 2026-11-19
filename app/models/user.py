from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.db.base import Base

if TYPE_CHECKING:
    from app.models.establishment import Establishment
    from app.models.oauth_login_code import OAuthLoginCode
    from app.models.phone_verification import PhoneVerificationCode
    from app.models.review import Review


# PENDING_PHONE: falta verificar el teléfono; SUSPENDED: sancionada por un admin (fase 2, B5);
# DELETED: el titular eliminó su cuenta (B8). La fila queda anonimizada como "lápida" para que la
# bitácora de moderación, los reportes y los consentimientos sigan apuntando a un id válido.
USER_STATUSES = {"PENDING_PHONE", "ACTIVE", "SUSPENDED", "DELETED"}
DELETED_USER_NAME = "Usuario eliminado"
USER_ROLES = {"user", "admin", "restaurant"}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    nickname: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    google_sub: Mapped[str | None] = mapped_column(String(255), unique=True, index=True, nullable=True)
    picture: Mapped[str | None] = mapped_column(String(500), nullable=True)
    phone_number: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    phone_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="PENDING_PHONE", nullable=False)
    # Motivo y fecha de la suspensión (status=SUSPENDED); se limpian al reactivar.
    suspension_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    # Copia de la última aceptación (el historial, prueba de la autorización, está en `consents`).
    privacy_policy_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    terms_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    consents_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Última descarga de "mis datos" (límite DATA_EXPORT_COOLDOWN_MINUTES).
    last_data_export_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    role: Mapped[str] = mapped_column(String(30), default="user", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    phone_verification_codes: Mapped[list["PhoneVerificationCode"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    oauth_login_codes: Mapped[list["OAuthLoginCode"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    establishments: Mapped[list["Establishment"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    # lazy="raise": las reseñas de un usuario se consultan siempre de forma explícita y paginada.
    # passive_deletes: al borrar el usuario las elimina el ON DELETE CASCADE de la base de datos.
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="author", cascade="all, delete-orphan", passive_deletes=True, lazy="raise"
    )

    @property
    def pending_consents(self) -> list[str]:
        """Documentos cuya versión vigente (configuración) el usuario aún no ha aceptado."""
        pending: list[str] = []
        if self.privacy_policy_version != settings.privacy_policy_version:
            pending.append("PRIVACY_POLICY")
        if self.terms_version != settings.terms_version:
            pending.append("TERMS")
        return pending
