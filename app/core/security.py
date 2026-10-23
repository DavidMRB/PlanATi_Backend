from datetime import datetime, timedelta, timezone
import secrets

import jwt
from fastapi import Response
from pwdlib import PasswordHash

from app.core.config import settings

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)


def set_auth_cookie(response: Response, token: str, *, max_age: int | None = None) -> None:
    response.set_cookie(
        key=settings.access_token_cookie_name,
        value=token,
        httponly=True,
        secure=settings.access_token_cookie_secure or settings.app_env == "production",
        samesite=settings.access_token_cookie_samesite,
        max_age=max_age if max_age is not None else settings.access_token_cookie_max_age_seconds,
        path=settings.access_token_cookie_path,
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(
        key=settings.access_token_cookie_name,
        path=settings.access_token_cookie_path,
    )


def create_access_token(subject: str) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.jwt_expiration_minutes)
    payload = {"sub": subject, "exp": expires_at}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def create_oauth_state() -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    return jwt.encode({"state": secrets.token_urlsafe(32), "exp": expires_at}, settings.secret_key, algorithm="HS256")


def verify_oauth_state(state: str) -> bool:
    try:
        jwt.decode(state, settings.secret_key, algorithms=["HS256"])
        return True
    except jwt.InvalidTokenError:
        return False
