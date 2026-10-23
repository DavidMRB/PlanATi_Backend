from datetime import datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.review import ReviewResponse


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


class EstablishmentResponse(BaseModel):
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
    schedules: list[ScheduleResponse] = Field(default_factory=list)
    menu_items: list[MenuItemResponse] = Field(default_factory=list)
    images: list[EstablishmentImageResponse] = Field(default_factory=list)
    reviews: list[ReviewResponse] = Field(default_factory=list)


class EstablishmentDetailResponse(EstablishmentResponse):
    """Detalle público: catálogo separado y resumen de reseñas en solo lectura."""

    products: list[MenuItemResponse] = Field(default_factory=list)
    combos: list[MenuItemResponse] = Field(default_factory=list)
    gallery_images: list[EstablishmentImageResponse] = Field(default_factory=list)
    menu_images: list[EstablishmentImageResponse] = Field(default_factory=list)
    reviews_count: int = 0
    average_rating: float | None = None


class EstablishmentNearbyResponse(EstablishmentResponse):
    distance_km: float = Field(ge=0)
