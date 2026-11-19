from datetime import datetime, timedelta, timezone
import secrets
from typing import Any

import jwt
from fastapi import Response
from pwdlib import PasswordHash

from app.core.config import Settings, settings

password_hash = PasswordHash.recommended()

JWT_ALGORITHM = "HS256"
OAUTH_STATE_COOKIE_NAME = "oauth_state"
OAUTH_STATE_MAX_AGE_SECONDS = 600


# Contraseñas: hash con Argon2 (pwdlib); nunca se guarda la contraseña en texto plano.
def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)


def cookie_is_secure(cfg: Settings) -> bool:
    """En producción `Secure` es obligatorio (se ignora ACCESS_TOKEN_COOKIE_SECURE=false)."""
    return cfg.access_token_cookie_secure or cfg.is_production


# GUIA #7 TEMA: Cadenas, listas, tuplas y diccionarios -> los atributos de la cookie se devuelven como diccionario y se desempaquetan con `**`.
def session_cookie_params() -> dict[str, Any]:
    """Atributos comunes de las cookies de sesión (`access_token` y `oauth_state`).

    Se usan al crearlas y al borrarlas: el navegador solo elimina una cookie si el borrado
    repite `path`, `domain`, `secure` y `samesite` con que se creó.
    """
    return {
        "httponly": True,
        "secure": cookie_is_secure(settings),
        "samesite": settings.access_token_cookie_samesite.strip().lower(),
        "path": settings.access_token_cookie_path,
        "domain": settings.access_token_cookie_domain.strip() or None,
    }


# GUIA #10 TEMA: Subalgoritmos (funciones, procedimientos y modularización) -> procedimiento (`-> None`): escribe la cookie de sesión HttpOnly en la respuesta.
def set_auth_cookie(response: Response, token: str, *, max_age: int | None = None) -> None:
    response.set_cookie(
        key=settings.access_token_cookie_name,
        value=token,
        max_age=max_age if max_age is not None else settings.access_token_cookie_max_age_seconds,
        **session_cookie_params(),
    )


def clear_auth_cookie(response: Response) -> None:
    response.delete_cookie(key=settings.access_token_cookie_name, **session_cookie_params())


def set_oauth_state_cookie(response: Response, state: str) -> None:
    response.set_cookie(
        key=OAUTH_STATE_COOKIE_NAME,
        value=state,
        max_age=OAUTH_STATE_MAX_AGE_SECONDS,
        **session_cookie_params(),
    )


def clear_oauth_state_cookie(response: Response) -> None:
    response.delete_cookie(key=OAUTH_STATE_COOKIE_NAME, **session_cookie_params())


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def create_access_token(subject: str, *, csrf_token: str | None = None) -> str:
    """JWT de sesión. Lleva el token CSRF de la sesión en el claim `csrf` (ver app/core/csrf.py)."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_expiration_minutes),
        "csrf": csrf_token or new_csrf_token(),
    }
    return jwt.encode(payload, settings.secret_key, algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    """Valida firma y expiración. Lanza `jwt.InvalidTokenError` si el token no sirve."""
    return jwt.decode(token, settings.secret_key, algorithms=[JWT_ALGORITHM])


def csrf_claim(token: str | None) -> str | None:
    """Token CSRF guardado en un JWT de sesión válido, o None (sin token, inválido o sin claim)."""
    if not token:
        return None
    try:
        claim = decode_access_token(token).get("csrf")
    except jwt.InvalidTokenError:
        return None
    return claim if isinstance(claim, str) and claim else None


def create_oauth_state() -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=OAUTH_STATE_MAX_AGE_SECONDS)
    return jwt.encode({"state": secrets.token_urlsafe(32), "exp": expires_at}, settings.secret_key, algorithm=JWT_ALGORITHM)


def verify_oauth_state(state: str) -> bool:
    try:
        jwt.decode(state, settings.secret_key, algorithms=[JWT_ALGORITHM])
        return True
    except jwt.InvalidTokenError:
        return False
