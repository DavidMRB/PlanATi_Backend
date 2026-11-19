from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.models.review import MODERATION_CATEGORIES
from app.schemas.establishment import EstablishmentImageResponse
from app.schemas.restaurant import RestaurantProfileUpdate
from app.schemas.review import ReviewImageResponse
from app.schemas.user import UserResponse

# Motivo obligatorio de suspensiones, borrados y rechazos (5..1000 caracteres, sin espacios a los lados).
Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=5, max_length=1000)]
OptionalNote = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None
ModerationCategory = Literal[
    "OFFENSIVE_LANGUAGE",
    "HATE_OR_DISCRIMINATION",
    "PERSONAL_DATA",
    "SPAM_OR_ADVERTISING",
    "FALSE_OR_MISLEADING",
    "SEXUAL_OR_VIOLENT",
    "ILLEGAL_CONTENT",
    "OFF_TOPIC",
    "OTHER",
]
assert set(ModerationCategory.__args__) == set(MODERATION_CATEGORIES)  # type: ignore[attr-defined]


def _empty_as_none(value: str | None) -> str | None:
    return value or None


class _NoteModel(BaseModel):
    note: OptionalNote = None

    _clean = field_validator("note")(_empty_as_none)


# --- Dashboard ---------------------------------------------------------------------------------


class AdminDashboardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    users_count: int
    establishments_count: int
    reviews_count: int
    pending_establishments: int = 0
    suspended_establishments: int = 0
    suspended_users: int = 0
    open_reports: int = 0
    hidden_reviews: int = 0
    # Comentarios de reseñas y respuestas bloqueados.
    blocked_comments: int = 0
    # Reseñas (o sus respuestas) reescritas tras un bloqueo, pendientes de revisión.
    flagged_for_review: int = 0
    reviews_last_7_days: int = 0
    # Planes SCHEDULED futuros.
    scheduled_plans: int = 0
    establishments_without_location: int = 0


# --- Usuarios ----------------------------------------------------------------------------------


class UserRoleUpdate(BaseModel):
    role: str = Field(min_length=3, max_length=30)


class AdminUserListItem(UserResponse):
    suspension_reason: str | None = None
    suspended_at: datetime | None = None
    reviews_count: int = 0
    # Reportes abiertos sobre la cuenta o sobre sus reseñas.
    open_reports_count: int = 0
    # Establecimiento de una cuenta `restaurant` (para ofrecer suspender también el local).
    establishment_id: int | None = None


class AdminUserEstablishment(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    status: str


class ReportSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    reporter_id: int
    target_type: str
    target_id: int
    reason: str
    details: str | None = None
    status: str
    created_at: datetime
    resolved_at: datetime | None = None
    resolution_note: str | None = None


class ModerationActionItem(BaseModel):
    id: int
    admin_id: int | None = None
    # None si la acción fue automática o el admin ya no existe.
    admin_name: str | None = None
    admin_email: str | None = None
    action: str
    target_type: str
    target_id: int
    reason: str | None = None
    details: dict[str, Any] | None = None
    created_at: datetime


class AdminReviewAuthor(BaseModel):
    id: int
    display_name: str
    full_name: str
    email: str
    status: str
    picture: str | None = None


class AdminReviewEstablishment(BaseModel):
    id: int
    name: str
    status: str


class AdminReplyItem(BaseModel):
    """Respuesta del establecimiento vista por el admin: siempre con el texto original."""

    id: int
    comment: str
    comment_status: str
    moderation_category: str | None = None
    moderation_reason: str | None = None
    flagged_for_review: bool = False
    created_at: datetime
    updated_at: datetime


class AdminReviewItem(BaseModel):
    """Reseña vista por el admin: siempre con el texto original, el autor (con email) y los reportes."""

    id: int
    establishment: AdminReviewEstablishment
    author: AdminReviewAuthor
    rating: int
    comment: str | None = None
    status: str
    comment_status: str
    moderation_category: str | None = None
    moderation_reason: str | None = None
    flagged_for_review: bool = False
    created_at: datetime
    edited_at: datetime | None = None
    images: list[ReviewImageResponse] = Field(default_factory=list)
    reply: AdminReplyItem | None = None
    open_reports_count: int = 0


class AdminUserDetail(AdminUserListItem):
    establishments: list[AdminUserEstablishment] = Field(default_factory=list)
    recent_reviews: list[AdminReviewItem] = Field(default_factory=list)
    # Reportes sobre la cuenta o sobre sus reseñas (los 10 más recientes, en cualquier estado).
    reports_received: list[ReportSummary] = Field(default_factory=list)
    moderation_history: list[ModerationActionItem] = Field(default_factory=list)


class SuspendRequest(BaseModel):
    reason: Reason


class ReactivateRequest(_NoteModel):
    pass


class AdminNotifyRequest(BaseModel):
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=150)]
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]
    # Ruta relativa del frontend, p. ej. "/profile".
    link: str | None = Field(default=None, max_length=300, pattern=r"^/[^\s]*$")


# --- Establecimientos --------------------------------------------------------------------------


class AdminEstablishmentListItem(BaseModel):
    id: int
    name: str
    category: str
    address: str
    owner_id: int
    owner_email: str
    manager_name: str | None = None
    phone: str | None = None
    contact_email: str | None = None
    status: str
    created_at: datetime
    establishment_type: str = "RESTAURANT"
    city: str | None = None
    rating_avg: float | None = None
    rating_count: int = 0
    has_location: bool = False
    open_reports_count: int = 0
    suspension_reason: str | None = None


class AdminEstablishmentDetail(AdminEstablishmentListItem):
    description: str
    rejection_reason: str | None = None
    profile_image_url: str | None = None
    banner_image_url: str | None = None
    owner_full_name: str
    owner_status: str
    images: list[EstablishmentImageResponse] = Field(default_factory=list)
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    location_source: str | None = None
    google_place_id: str | None = None
    price_range: str | None = None
    ranking_score: float | None = None


class EstablishmentRejectRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


class EstablishmentDecisionResponse(BaseModel):
    id: int
    status: Literal["APPROVED", "REJECTED", "SUSPENDED"]
    rejection_reason: str | None = None
    suspension_reason: str | None = None
    message: str
    # Avisos que no impiden la decisión (p. ej. un local sin ubicación no aparecerá en el mapa).
    warnings: list[str] = Field(default_factory=list)


class AdminEstablishmentUpdate(RestaurantProfileUpdate):
    """Editar como el establecimiento; `reason` (opcional) se guarda en la bitácora y se envía al dueño."""

    reason: OptionalNote = None

    _clean_reason = field_validator("reason")(_empty_as_none)


# --- Moderación de reseñas ---------------------------------------------------------------------


class BlockCommentRequest(_NoteModel):
    category: ModerationCategory
    remove_images: bool = False


class BlockReplyRequest(_NoteModel):
    category: ModerationCategory


class UnblockRequest(_NoteModel):
    pass


class HideReviewRequest(BaseModel):
    category: ModerationCategory
    # Nota para el autor; se acepta también como `note`.
    reason: OptionalNote = Field(default=None, validation_alias=AliasChoices("reason", "note"))

    _clean = field_validator("reason")(_empty_as_none)


class RestoreReviewRequest(_NoteModel):
    pass


# --- Reportes ----------------------------------------------------------------------------------


class ReportTargetPreview(BaseModel):
    exists: bool
    # Visible para el público (aprobado, no oculto, no suspendido).
    visible: bool = False
    owner_id: int | None = None
    establishment_id: int | None = None
    name: str | None = None
    # Texto original (el admin lo ve aunque esté bloqueado).
    text: str | None = None
    image_url: str | None = None
    rating: int | None = None
    status: str | None = None
    comment_status: str | None = None
    owner_name: str | None = None
    review_id: int | None = None
    establishment_name: str | None = None
    is_available: bool | None = None


class AdminReportItem(ReportSummary):
    reporter_name: str | None = None
    reporter_email: str | None = None
    resolved_by_id: int | None = None
    # Reportes abiertos sobre el mismo destino (incluido este si sigue abierto).
    reports_on_target: int = 0
    preview: ReportTargetPreview


class ResolveReportRequest(_NoteModel):
    action: Literal["NONE", "BLOCK_COMMENT", "HIDE_CONTENT", "DELETE_CONTENT", "SUSPEND_OWNER"]
    # Obligatoria salvo con action=NONE.
    category: ModerationCategory | None = None


class DismissReportRequest(_NoteModel):
    pass
