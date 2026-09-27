from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ReviewImageCreate(BaseModel):
    image_url: str = Field(min_length=1, max_length=500)


class ReviewImageResponse(ReviewImageCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class ReviewCreate(BaseModel):
    rating: int = Field(ge=1, le=5)
    comment: str = Field(min_length=1)
    image_urls: list[str] = Field(default_factory=list)


class ReviewReplyCreate(BaseModel):
    comment: str = Field(min_length=1)


class ReviewReplyResponse(ReviewReplyCreate):
    model_config = ConfigDict(from_attributes=True)

    id: int
    establishment_id: int
    created_at: datetime


class ReviewResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    establishment_id: int
    rating: int
    comment: str
    created_at: datetime
    images: list[ReviewImageResponse] = Field(default_factory=list)
    reply: ReviewReplyResponse | None = None
