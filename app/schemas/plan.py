from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, Field, StringConstraints, field_validator

PlanStatus = Literal["SCHEDULED", "CANCELLED", "COMPLETED"]
ReminderMinutes = Literal[15, 30, 60, 120, 1440]
MAX_PLAN_ITEMS = 30
MAX_QUANTITY = 99

_Title = Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]
_Notes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]
_ItemNotes = Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)]


def _empty_as_none(value: str | None) -> str | None:
    return value or None


class PlanItemInput(BaseModel):
    menu_item_id: int = Field(gt=0)
    quantity: int = Field(default=1, ge=1, le=MAX_QUANTITY)
    notes: _ItemNotes | None = None  # p. ej. "sin cebolla"

    _clean = field_validator("notes")(_empty_as_none)


def merge_items(items: list[PlanItemInput]) -> list[PlanItemInput]:
    """Los ítems repetidos se fusionan sumando cantidades (se conserva la primera nota no vacía)."""
    merged: dict[int, PlanItemInput] = {}
    for item in items:
        current = merged.get(item.menu_item_id)
        if current is None:
            merged[item.menu_item_id] = item.model_copy()
            continue
        quantity = current.quantity + item.quantity
        if quantity > MAX_QUANTITY:
            raise ValueError(f"La cantidad de un mismo plato no puede superar {MAX_QUANTITY}.")
        merged[item.menu_item_id] = current.model_copy(
            update={"quantity": quantity, "notes": current.notes or item.notes}
        )
    return list(merged.values())


class PlanCreate(BaseModel):
    establishment_id: int = Field(gt=0)
    # Con zona horaria obligatoria (sin offset → 422), p. ej. "2026-11-20T19:30:00-05:00".
    scheduled_at: AwareDatetime
    party_size: int = Field(default=1, ge=1, le=50)
    # Vacío = "Plan en {nombre del local}".
    title: _Title | None = None
    notes: _Notes | None = None
    reminder_minutes_before: ReminderMinutes | None = None
    items: list[PlanItemInput] = Field(default_factory=list, max_length=MAX_PLAN_ITEMS)

    _clean = field_validator("title", "notes")(_empty_as_none)
    _merge = field_validator("items")(merge_items)


class PlanUpdate(BaseModel):
    """Campos opcionales. `items` (si llega) reemplaza la lista y recalcula el total con precios actuales."""

    scheduled_at: AwareDatetime | None = None
    party_size: int | None = Field(default=None, ge=1, le=50)
    title: _Title | None = None
    notes: _Notes | None = None
    reminder_minutes_before: ReminderMinutes | None = None
    items: list[PlanItemInput] | None = Field(default=None, max_length=MAX_PLAN_ITEMS)

    _clean = field_validator("title", "notes")(_empty_as_none)

    @field_validator("items")
    @classmethod
    def _merge_items(cls, value: list[PlanItemInput] | None) -> list[PlanItemInput] | None:
        if value is None:
            raise ValueError("Envía la lista de platos (puede ser vacía).")
        return merge_items(value)

    @field_validator("scheduled_at", "party_size")
    @classmethod
    def _not_null(cls, value: object) -> object:
        if value is None:
            raise ValueError("Este campo no puede quedar vacío.")
        return value


class PlanEstablishment(BaseModel):
    id: int
    name: str
    address: str
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    profile_image_url: str | None = None


class PlanListItem(BaseModel):
    id: int
    title: str
    scheduled_at: datetime
    party_size: int
    status: PlanStatus
    reminder_minutes_before: int | None = None
    reminder_at: datetime | None = None
    total_amount: Decimal
    currency: str
    # Número de líneas (platos o combos distintos) del plan.
    items_count: int = 0
    establishment: PlanEstablishment
    created_at: datetime
    updated_at: datetime


class PlanItemResponse(BaseModel):
    id: int
    menu_item_id: int | None = None
    # Nombre y precio congelados al planear.
    name: str
    unit_price: Decimal
    quantity: int
    subtotal: Decimal
    notes: str | None = None
    # Precio actual del catálogo; None si el producto se borró o ya no está disponible.
    current_price: Decimal | None = None
    # El precio actual difiere del congelado, o el producto se borró o ya no está disponible.
    price_changed: bool = False


class PlanDetail(PlanListItem):
    notes: str | None = None
    reminder_sent_at: datetime | None = None
    items: list[PlanItemResponse] = Field(default_factory=list)
    # False si el local ya no está aprobado (p. ej. suspendido).
    establishment_available: bool = True
    # Con los horarios actuales el local ya no abre a esa hora.
    outside_schedule: bool = False
    # Algún ítem tiene `price_changed`.
    prices_changed: bool = False
