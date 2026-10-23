from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    full_name: str
    nickname: str | None = None
    email: str
    role: str
    google_sub: str | None = None
    picture: str | None = None
    phone_number: str | None = None
    phone_verified: bool
    status: str
    created_at: datetime


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=120)
    nickname: str | None = Field(default=None, min_length=2, max_length=50)
    picture: str | None = Field(default=None, max_length=500)
    phone_number: str | None = Field(default=None, min_length=10, max_length=20)
