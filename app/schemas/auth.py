from pydantic import BaseModel, Field

from app.schemas.privacy import ConsentAcceptance


class RegisterRequest(ConsentAcceptance):
    full_name: str = Field(min_length=2, max_length=120)
    nickname: str | None = Field(default=None, min_length=2, max_length=50)
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    phone_number: str = Field(min_length=10, max_length=20)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=1, max_length=128)


class AuthResponse(BaseModel):
    registration_complete: bool
    requires_phone_verification: bool
    role: str | None = None
    establishment_status: str | None = None
    # Token CSRF de la sesión recién creada (no es el JWT y por sí solo no autentica).
    # El frontend lo guarda en memoria y lo envía en la cabecera X-CSRF-Token.
    csrf_token: str


class CsrfTokenResponse(BaseModel):
    csrf_token: str


class TokenResponse(AuthResponse):
    pass


class GoogleAuthResponse(AuthResponse):
    authenticated: bool = True


class GoogleExchangeRequest(BaseModel):
    code: str = Field(min_length=8, max_length=255)


class PhoneCodeRequest(BaseModel):
    phone_number: str = Field(min_length=10, max_length=20)


class PhoneVerifyRequest(PhoneCodeRequest):
    code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")


class PhoneVerificationResponse(BaseModel):
    success: bool = True
    phone_verified: bool = True
    registration_complete: bool = True
