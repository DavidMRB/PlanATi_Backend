from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    nickname: str | None = Field(default=None, min_length=2, max_length=50)
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    phone_number: str = Field(min_length=10, max_length=20)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    registration_complete: bool
    requires_phone_verification: bool


class GoogleAuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    authenticated: bool = True
    registration_complete: bool
    requires_phone_verification: bool


class PhoneCodeRequest(BaseModel):
    phone_number: str = Field(min_length=10, max_length=20)


class PhoneVerifyRequest(PhoneCodeRequest):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class PhoneVerificationResponse(BaseModel):
    success: bool = True
    phone_verified: bool = True
    registration_complete: bool = True
