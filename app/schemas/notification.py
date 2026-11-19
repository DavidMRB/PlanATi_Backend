from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, computed_field, field_validator

from app.core.time import ensure_utc


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    type: str
    title: str
    body: str
    link: str | None = None
    data: dict[str, Any] | None = None
    read_at: datetime | None = None
    created_at: datetime

    @field_validator("read_at", "created_at")
    @classmethod
    def _as_utc(cls, value: datetime | None) -> datetime | None:
        # SQLite devuelve fechas sin zona; la API siempre responde en UTC con offset.
        return ensure_utc(value) if value is not None else None

    @computed_field
    @property
    def is_read(self) -> bool:
        return self.read_at is not None


class UnreadCountResponse(BaseModel):
    count: int
