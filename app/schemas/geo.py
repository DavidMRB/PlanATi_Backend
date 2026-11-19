"""Tipos comunes de ubicación para los esquemas de establecimientos."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, Field

COORDINATE_STEP = Decimal("0.000001")  # 6 decimales ≈ 11 cm, igual que Numeric(9, 6) en la base de datos

LocationSource = Literal["GPS", "ADDRESS", "MAP_PIN", "MANUAL"]
EstablishmentType = Literal["RESTAURANT", "CAFE", "BAR", "HOTEL", "EXPERIENCE", "STORE", "OTHER"]


def _round_coordinate(value: Decimal) -> Decimal:
    # El GPS y Google Maps entregan más de 6 decimales: se redondean en vez de rechazar la petición.
    return value.quantize(COORDINATE_STEP, rounding=ROUND_HALF_UP)


Latitude = Annotated[Decimal, Field(ge=-90, le=90), AfterValidator(_round_coordinate)]
Longitude = Annotated[Decimal, Field(ge=-180, le=180), AfterValidator(_round_coordinate)]


def check_coordinates_pair(model: BaseModel) -> None:
    """Latitud y longitud se envían juntas o ninguna; si se envían, no pueden ser nulas."""
    sent = {"latitude", "longitude"} & model.model_fields_set
    if not sent:
        return
    if sent != {"latitude", "longitude"}:
        raise ValueError("Envía la latitud y la longitud juntas.")
    if getattr(model, "latitude") is None or getattr(model, "longitude") is None:
        raise ValueError("La ubicación del establecimiento es obligatoria: envía latitud y longitud.")


def clean_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None
