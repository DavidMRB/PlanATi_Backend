from datetime import datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.review import MyReview, ReviewBlockReason, ReviewPublic


class ScheduleInput(BaseModel):
    day_of_week: int = Field(ge=0, le=6)
    opening_time: time
    closing_time: time


class ScheduleResponse(ScheduleInput):
    model_config = ConfigDict(from_attributes=True)

    id: int


class MenuItemInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    price: Decimal = Field(ge=0, decimal_places=2)


class ComboItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    product_id: int
    quantity: int
    product_name: str | None = None


class MenuItemResponse(MenuItemInput):
    model_config = ConfigDict(from_attributes=True)

    id: int
    image_url: str | None = None
    is_combo: bool = False
    is_available: bool = True
    combo_items: list[ComboItemResponse] = Field(default_factory=list)


class EstablishmentImageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    image_url: str
    image_type: str
    caption: str | None = None
    display_order: int


class EstablishmentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    category: str = Field(min_length=2, max_length=80)
    description: str = Field(min_length=1)
    address: str = Field(min_length=2, max_length=255)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90, decimal_places=6)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180, decimal_places=6)
    price_range: str | None = Field(default=None, max_length=20)
    schedules: list[ScheduleInput] = Field(default_factory=list)
    menu_items: list[MenuItemInput] = Field(default_factory=list)


class EstablishmentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    category: str | None = Field(default=None, min_length=2, max_length=80)
    description: str | None = Field(default=None, min_length=1)
    address: str | None = Field(default=None, min_length=2, max_length=255)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90, decimal_places=6)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180, decimal_places=6)
    price_range: str | None = Field(default=None, max_length=20)
    schedules: list[ScheduleInput] | None = None
    menu_items: list[MenuItemInput] | None = None


class EstablishmentListItem(BaseModel):
    """Elemento del directorio y de cercanos: sin reseñas; la puntuación llega ya agregada."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    owner_id: int
    name: str
    category: str
    description: str
    address: str
    latitude: Decimal | None
    longitude: Decimal | None
    price_range: str | None
    status: str = "PENDING"
    phone: str | None = None
    contact_email: str | None = None
    profile_image_url: str | None = None
    banner_image_url: str | None = None
    manager_name: str | None = None
    created_at: datetime
    establishment_type: str = "RESTAURANT"
    city: str | None = None
    location_source: str | None = None
    google_place_id: str | None = None
    rating_avg: float | None = None
    rating_count: int = 0
    ranking_score: float | None = None
    schedules: list[ScheduleResponse] = Field(default_factory=list)
    # Se conserva porque la página de inicio arma "experiencias" con los combos del listado.
    # Pendiente: sustituirlo por un endpoint de combos destacados.
    menu_items: list[MenuItemResponse] = Field(default_factory=list)
    images: list[EstablishmentImageResponse] = Field(default_factory=list)


class EstablishmentResponse(EstablishmentListItem):
    """Perfil del establecimiento (panel del restaurante, alta y edición). Sin reseñas: se piden
    paginadas en GET /reviews/establishments/{id}."""


class EstablishmentDetailResponse(EstablishmentResponse):
    """Detalle público: catálogo separado y resumen de reseñas.

    `reviews` ya no existe: llegan las 3 más recientes en `recent_reviews` y el resto en el
    endpoint paginado de reseñas.
    """

    products: list[MenuItemResponse] = Field(default_factory=list)
    combos: list[MenuItemResponse] = Field(default_factory=list)
    gallery_images: list[EstablishmentImageResponse] = Field(default_factory=list)
    menu_images: list[EstablishmentImageResponse] = Field(default_factory=list)
    # Leen los agregados `rating_count` y `rating_avg` (solo reseñas visibles).
    reviews_count: int = 0
    average_rating: float | None = None
    rating_distribution: dict[str, int] = Field(default_factory=lambda: {str(n): 0 for n in range(1, 6)})
    # Puesto entre los aprobados de la misma categoría por ranking_score (1 = el mejor).
    category_rank: int | None = None
    recent_reviews: list[ReviewPublic] = Field(default_factory=list)
    # Reseña del usuario que consulta, en cualquier estado (para que vea si fue ocultada o bloqueada).
    viewer_review: MyReview | None = None
    viewer_can_review: bool = False
    viewer_review_block: ReviewBlockReason | None = None
    # B7: si el usuario que consulta lo tiene en favoritos (false sin sesión).
    is_favorite: bool = False


class EstablishmentNearbyItem(EstablishmentListItem):
    distance_km: float = Field(ge=0)


class MapMarker(BaseModel):
    id: int
    name: str
    category: str
    establishment_type: str
    latitude: Decimal
    longitude: Decimal
    rating_avg: float | None = None
    rating_count: int = 0
    price_range: str | None = None
    profile_image_url: str | None = None


class MapMarkersResponse(BaseModel):
    items: list[MapMarker]
    # True si en el área había más locales que `limit`: se devolvieron los mejor posicionados.
    truncated: bool
