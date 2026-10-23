import re
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field, field_validator

EMAIL_PATTERN = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
IMAGE_URL_PATTERN = r"^https?://\S+$"
PHONE_PATTERN = re.compile(r"^\+?\d{10,19}$")


def normalize_establishment_phone(value: str) -> str:
    normalized = re.sub(r"[\s\-()]", "", value)
    if not PHONE_PATTERN.fullmatch(normalized):
        raise ValueError("El teléfono debe contener entre 10 y 20 dígitos")
    return normalized


def validate_strong_password(value: str) -> str:
    if (
        len(value) < 8
        or not re.search(r"[A-Z]", value)
        or not re.search(r"\d", value)
        or not re.search(r"[^A-Za-z0-9]", value)
    ):
        raise ValueError(
            "La contraseña debe tener al menos 8 caracteres, una mayúscula, un número y un símbolo"
        )
    return value


class RestaurantRegisterRequest(BaseModel):
    account_email: str = Field(min_length=5, max_length=255, pattern=EMAIL_PATTERN)
    password: str = Field(min_length=8, max_length=128)
    manager_name: str = Field(min_length=2, max_length=120)
    establishment_name: str = Field(min_length=2, max_length=150)
    category: str = Field(min_length=2, max_length=80)
    address: str = Field(min_length=2, max_length=255)
    establishment_phone: str = Field(min_length=10, max_length=25)
    contact_email: str = Field(min_length=5, max_length=255, pattern=EMAIL_PATTERN)
    description: str = Field(min_length=1)
    profile_image_url: str | None = Field(default=None, max_length=500, pattern=IMAGE_URL_PATTERN)
    banner_image_url: str | None = Field(default=None, max_length=500, pattern=IMAGE_URL_PATTERN)

    _check_password = field_validator("password")(validate_strong_password)
    _check_phone = field_validator("establishment_phone")(normalize_establishment_phone)


class RestaurantRegisterResponse(BaseModel):
    user_id: int
    establishment_id: int
    role: str
    establishment_status: str
    message: str


class RestaurantStatusResponse(BaseModel):
    establishment_id: int
    name: str
    category: str
    address: str
    status: str
    rejection_reason: str | None = None


class RestaurantProfileUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    category: str | None = Field(default=None, min_length=2, max_length=80)
    address: str | None = Field(default=None, min_length=2, max_length=255)
    phone: str | None = Field(default=None, min_length=10, max_length=25)
    contact_email: str | None = Field(default=None, min_length=5, max_length=255, pattern=EMAIL_PATTERN)
    description: str | None = Field(default=None, min_length=1)
    profile_image_url: str | None = Field(default=None, max_length=500, pattern=IMAGE_URL_PATTERN)
    banner_image_url: str | None = Field(default=None, max_length=500, pattern=IMAGE_URL_PATTERN)
    manager_name: str | None = Field(default=None, min_length=2, max_length=120)
    latitude: Decimal | None = Field(default=None, ge=-90, le=90, decimal_places=6)
    longitude: Decimal | None = Field(default=None, ge=-180, le=180, decimal_places=6)
    price_range: str | None = Field(default=None, max_length=20)

    @field_validator("phone")
    @classmethod
    def _check_phone(cls, value: str | None) -> str | None:
        return normalize_establishment_phone(value) if value is not None else None


class RestaurantReapplyResponse(BaseModel):
    establishment_id: int
    status: str
    message: str


class UploadUrlResponse(BaseModel):
    upload_url: str
    public_url: str
    key: str


class EstablishmentImageCreate(BaseModel):
    image_url: str = Field(max_length=500, pattern=IMAGE_URL_PATTERN)
    image_type: Literal["GALLERY", "MENU"]
    caption: str | None = Field(default=None, max_length=150)
    display_order: int = Field(default=0, ge=0)


class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    price: Decimal = Field(ge=0, max_digits=10, decimal_places=2)
    image_url: str | None = Field(default=None, max_length=500, pattern=IMAGE_URL_PATTERN)
    is_available: bool = True


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    price: Decimal | None = Field(default=None, ge=0, max_digits=10, decimal_places=2)
    image_url: str | None = Field(default=None, max_length=500, pattern=IMAGE_URL_PATTERN)
    is_available: bool | None = None


class ComboItemInput(BaseModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(default=1, ge=1, le=100)


class ComboCreate(ProductCreate):
    # Lista vacía: combo unitario independiente. Con elementos: combo compuesto por productos del catálogo.
    items: list[ComboItemInput] = Field(default_factory=list)


class ComboUpdate(ProductUpdate):
    # None conserva la composición actual; una lista (incluso vacía) la reemplaza.
    items: list[ComboItemInput] | None = None

