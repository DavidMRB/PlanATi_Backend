from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

ReportTargetType = Literal[
    "REVIEW", "REVIEW_REPLY", "REVIEW_IMAGE", "ESTABLISHMENT", "ESTABLISHMENT_IMAGE", "MENU_ITEM", "USER"
]
ReportReason = Literal["SPAM", "OFFENSIVE", "FALSE_INFO", "INAPPROPRIATE_IMAGE", "OTHER"]


class ReportCreate(BaseModel):
    target_type: ReportTargetType
    target_id: int = Field(gt=0)
    reason: ReportReason
    details: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] | None = None

    @field_validator("details")
    @classmethod
    def _empty_as_none(cls, value: str | None) -> str | None:
        return value or None


class ReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    target_type: str
    target_id: int
    reason: str
    details: str | None = None
    status: str
    created_at: datetime
