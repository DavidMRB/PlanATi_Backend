from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.establishment import EstablishmentImageResponse


class UserRoleUpdate(BaseModel):
    role: str = Field(min_length=3, max_length=30)


class AdminDashboardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    users_count: int
    establishments_count: int
    reviews_count: int


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


class AdminEstablishmentDetail(AdminEstablishmentListItem):
    description: str
    rejection_reason: str | None = None
    profile_image_url: str | None = None
    banner_image_url: str | None = None
    owner_full_name: str
    owner_status: str
    images: list[EstablishmentImageResponse] = Field(default_factory=list)


class EstablishmentRejectRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=1000)


class EstablishmentDecisionResponse(BaseModel):
    id: int
    status: Literal["APPROVED", "REJECTED"]
    rejection_reason: str | None = None
    message: str
