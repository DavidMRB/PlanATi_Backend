from pydantic import BaseModel, ConfigDict, Field


class UserRoleUpdate(BaseModel):
    role: str = Field(min_length=3, max_length=30)


class AdminDashboardResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    users_count: int
    establishments_count: int
    reviews_count: int
