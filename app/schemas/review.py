from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.config import settings

ReviewSort = Literal["recent", "rating_desc", "rating_asc"]
# Motivo por el que el usuario que consulta no puede reseñar (`viewer_review_block`).
ReviewBlockReason = Literal[
    "LOGIN_REQUIRED", "PHONE_NOT_VERIFIED", "ROLE_NOT_ALLOWED", "OWNER", "ALREADY_REVIEWED", "SUSPENDED"
]


def review_images_prefix() -> str:
    """Las imágenes de reseñas solo pueden venir de la carpeta `reviews/` de nuestro bucket."""
    return f"{settings.r2_public_base_url.rstrip('/')}/reviews/"


def normalize_comment(value: str | None) -> str | None:
    """`strip()`; un texto vacío equivale a no escribir comentario."""
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > settings.review_comment_max_length:
        raise ValueError(f"El comentario no puede superar {settings.review_comment_max_length} caracteres.")
    return value


def validate_review_image_urls(urls: list[str]) -> list[str]:
    cleaned = [url.strip() for url in urls]
    if len(cleaned) > settings.review_max_images:
        raise ValueError(f"Puedes adjuntar como máximo {settings.review_max_images} imágenes.")
    if len(set(cleaned)) != len(cleaned):
        raise ValueError("Hay imágenes repetidas.")
    prefix = review_images_prefix()
    for url in cleaned:
        if len(url) > 500 or not url.startswith(prefix) or len(url) == len(prefix):
            raise ValueError("Las imágenes deben subirse con POST /reviews/upload-url.")
    return cleaned


class ReviewImageCreate(BaseModel):
    image_url: str = Field(min_length=1, max_length=500)

    @field_validator("image_url")
    @classmethod
    def _check_url(cls, value: str) -> str:
        return validate_review_image_urls([value])[0]


class ReviewImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    image_url: str
    display_order: int = 0
    created_at: datetime


class ReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5, strict=True)
    comment: str | None = None
    image_urls: list[str] = Field(default_factory=list)

    @field_validator("comment")
    @classmethod
    def _check_comment(cls, value: str | None) -> str | None:
        return normalize_comment(value)

    @field_validator("image_urls")
    @classmethod
    def _check_images(cls, value: list[str]) -> list[str]:
        return validate_review_image_urls(value)


class ReviewUpdate(BaseModel):
    """Campos opcionales; `image_urls` es la lista completa que reemplaza las imágenes actuales."""

    rating: int | None = Field(default=None, ge=1, le=5, strict=True)
    comment: str | None = None
    image_urls: list[str] | None = None

    @field_validator("comment")
    @classmethod
    def _check_comment(cls, value: str | None) -> str | None:
        return normalize_comment(value)

    @field_validator("image_urls")
    @classmethod
    def _check_images(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else validate_review_image_urls(value)

    @field_validator("rating")
    @classmethod
    def _rating_not_null(cls, value: int | None) -> int:
        if value is None:
            raise ValueError("La puntuación es obligatoria.")
        return value


class ReviewReplyCreate(BaseModel):
    comment: str = Field(min_length=1, max_length=1000)

    @field_validator("comment")
    @classmethod
    def _strip(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("La respuesta no puede estar vacía.")
        return value


class ReviewReplyResponse(BaseModel):
    """Respuesta de la ruta legada POST /reviews/{id}/reply (la escribe el propio establecimiento)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    establishment_id: int
    comment: str
    created_at: datetime


class ReviewAuthor(BaseModel):
    id: int
    # Apodo, o primer nombre + inicial ("Laura G."); nunca email, teléfono ni nombre completo.
    display_name: str
    picture: str | None = None


class ReviewReplyPublic(BaseModel):
    id: int
    created_at: datetime
    updated_at: datetime
    comment: str | None  # null si está bloqueada
    comment_blocked: bool = False
    moderation_notice: str | None = None


class ReviewPublic(BaseModel):
    """Única forma pública de una reseña: se construye solo con `review_service.to_public_review`."""

    id: int
    establishment_id: int
    rating: int
    comment: str | None  # null si no escribió texto o si está bloqueado
    comment_blocked: bool = False
    moderation_notice: str | None = None
    created_at: datetime
    edited_at: datetime | None = None
    status: str
    author: ReviewAuthor
    images: list[ReviewImageResponse] = Field(default_factory=list)
    reply: ReviewReplyPublic | None = None


class ReviewEstablishmentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    profile_image_url: str | None = None


class MyReview(ReviewPublic):
    """Vista del autor: `comment` es su texto original aunque esté bloqueado, más el estado de moderación."""

    comment_status: str
    moderation_category: str | None = None
    moderation_reason: str | None = None
    flagged_for_review: bool = False
    establishment: ReviewEstablishmentSummary


class RestaurantReviewSummary(BaseModel):
    """Resumen de reseñas para el panel del establecimiento (solo reseñas visibles)."""

    rating_avg: float | None = None
    rating_count: int = 0
    ranking_score: float | None = None
    category_rank: int | None = None
    distribution: dict[str, int]
    unanswered_count: int = 0
    # Proporción de reseñas visibles con respuesta (0..1); null si aún no hay reseñas.
    response_rate: float | None = None
