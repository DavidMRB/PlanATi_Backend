from datetime import datetime
from typing import TYPE_CHECKING

import sqlalchemy as sa
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.establishment import Establishment
    from app.models.user import User

# Estado de la reseña completa: HIDDEN la retira del público y del promedio (spam, reseña falsa).
REVIEW_STATUSES = {"VISIBLE", "HIDDEN"}
# Estado solo del texto: BLOCKED lo sustituye en público por un aviso; las estrellas siguen contando.
COMMENT_STATUSES = {"VISIBLE", "BLOCKED"}
BLOCKED_COMMENT_NOTICE = "El comentario fue bloqueado por una violación a las políticas de la aplicación."
BLOCKED_REPLY_NOTICE = "La respuesta fue bloqueada por una violación a las políticas de la aplicación."

# Deben coincidir con las secciones de las normas de la comunidad del frontend.
MODERATION_CATEGORIES = {
    "OFFENSIVE_LANGUAGE": "Lenguaje ofensivo o insultos",
    "HATE_OR_DISCRIMINATION": "Discriminación o discurso de odio",
    "PERSONAL_DATA": "Datos personales de terceros",
    "SPAM_OR_ADVERTISING": "Spam o publicidad",
    "FALSE_OR_MISLEADING": "Información falsa o engañosa",
    "SEXUAL_OR_VIOLENT": "Contenido sexual o violento",
    "ILLEGAL_CONTENT": "Contenido ilegal",
    "OFF_TOPIC": "No relacionado con el lugar",
    "OTHER": "Otro motivo",
}


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (
        UniqueConstraint("user_id", "establishment_id", name="uq_reviews_user_establishment"),
        CheckConstraint("rating BETWEEN 1 AND 5", name="ck_reviews_rating_range"),
        Index("ix_reviews_establishment_status_created", "establishment_id", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    establishment_id: Mapped[int] = mapped_column(
        ForeignKey("establishments.id", ondelete="CASCADE"), nullable=False
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    # Opcional: una reseña puede ser solo estrellas.
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="VISIBLE", server_default="VISIBLE", nullable=False)
    comment_status: Mapped[str] = mapped_column(
        String(20), default="VISIBLE", server_default="VISIBLE", nullable=False
    )
    moderation_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Nota del admin para el autor.
    moderation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # True si el autor reescribió un comentario bloqueado: queda pendiente de revisión del admin.
    flagged_for_review: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa.false(), nullable=False
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    images: Mapped[list["ReviewImage"]] = relationship(
        back_populates="review",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="(ReviewImage.display_order, ReviewImage.id)",
    )
    reply: Mapped["ReviewReply | None"] = relationship(
        back_populates="review", cascade="all, delete-orphan", lazy="selectin", uselist=False
    )
    establishment: Mapped["Establishment"] = relationship("Establishment", back_populates="reviews")
    author: Mapped["User"] = relationship(back_populates="reviews", lazy="selectin")


class ReviewImage(Base):
    __tablename__ = "review_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False)
    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    review: Mapped[Review] = relationship(back_populates="images")


class ReviewReply(Base):
    __tablename__ = "review_replies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[int] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    establishment_id: Mapped[int] = mapped_column(
        ForeignKey("establishments.id", ondelete="CASCADE"), nullable=False
    )
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    comment_status: Mapped[str] = mapped_column(
        String(20), default="VISIBLE", server_default="VISIBLE", nullable=False
    )
    moderation_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    moderation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    flagged_for_review: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default=sa.false(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    review: Mapped[Review] = relationship(back_populates="reply")
    establishment: Mapped["Establishment"] = relationship("Establishment")
