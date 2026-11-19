"""Protección CSRF en dos capas para la sesión por cookie HttpOnly.

Capa 1 — verificación de origen (todas las peticiones POST, PUT, PATCH y DELETE):
    * con `Authorization: Bearer …` la petición queda exenta (el navegador no añade esa cabecera
      por su cuenta, así que no es atacable por CSRF);
    * si trae `Origin`, debe estar en `CSRF_TRUSTED_ORIGINS` (por defecto CORS_ORIGINS + FRONTEND_URL);
    * sin `Origin`, se compara el origen del `Referer`;
    * sin ninguno de los dos, se rechaza solo si trae la cookie de sesión (los navegadores actuales
      siempre envían `Origin` en estas peticiones; `curl` sin cookie sigue funcionando).
    Aplica también a login y registros para evitar el "login CSRF".

Capa 2 — token por sesión (peticiones que cambian estado autenticadas por cookie):
    el JWT de sesión lleva el claim `csrf`; la cabecera `X-CSRF-Token` debe coincidir con él.
    El frontend lo recibe en `csrf_token` al iniciar sesión y con `GET /auth/csrf` al recargar.
    Exentas del token (no del origen): las rutas que crean la sesión y el logout.
"""

import logging
import secrets
from typing import NoReturn
from urllib.parse import urlsplit

import jwt
from fastapi import Request
from fastapi.security.utils import get_authorization_scheme_param

from app.core.config import settings
from app.core.security import decode_access_token

logger = logging.getLogger(__name__)

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_FAILED_CODE = "CSRF_FAILED"
CSRF_FAILED_DETAIL = "La solicitud fue rechazada por seguridad. Recarga la página e inténtalo de nuevo."

# Exentas del token (no de la verificación de origen): crean la sesión o la cierran.
TOKEN_EXEMPT_PATHS = frozenset(
    f"{settings.api_v1_prefix}{path}"
    for path in (
        "/auth/login",
        "/auth/register",
        "/auth/restaurant/register",
        "/auth/google/exchange",
        "/auth/logout",
    )
)


class CsrfError(Exception):
    """Petición rechazada por CSRF; `app/main.py` la convierte en 403 `{"detail", "code"}`."""

    def __init__(self, reason: str) -> None:
        # El motivo solo va a los logs: al cliente siempre se le da el mismo mensaje.
        self.reason = reason
        self.detail = CSRF_FAILED_DETAIL
        self.code = CSRF_FAILED_CODE
        super().__init__(reason)


def has_bearer_credentials(request: Request) -> bool:
    """Mismo criterio que `HTTPBearer`: esquema Bearer con credenciales no vacías."""
    scheme, credentials = get_authorization_scheme_param(request.headers.get("Authorization"))
    return scheme.lower() == "bearer" and bool(credentials)


def request_origin(request: Request) -> str | None:
    """Origen declarado por el navegador (`Origin`, o el del `Referer`), o None si no envía ninguno."""
    origin = request.headers.get("origin")
    if origin:
        return origin.strip().rstrip("/").lower()
    referer = request.headers.get("referer")
    if referer:
        parts = urlsplit(referer.strip())
        if parts.scheme and parts.netloc:
            return f"{parts.scheme}://{parts.netloc}".lower()
        return "null"  # Referer malformado: nunca es un origen de confianza.
    return None


def _session_csrf_claim(session_token: str | None) -> tuple[bool, str | None]:
    """(la cookie es una sesión válida, token CSRF de esa sesión)."""
    if not session_token:
        return False, None
    try:
        payload = decode_access_token(session_token)
    except jwt.InvalidTokenError:
        return False, None
    claim = payload.get("csrf")
    return True, claim if isinstance(claim, str) and claim else None


async def csrf_protect(request: Request) -> None:
    """Dependencia global registrada en `FastAPI(dependencies=[...])`."""
    if request.method.upper() not in UNSAFE_METHODS:
        return
    if has_bearer_credentials(request):
        return

    session_token = request.cookies.get(settings.access_token_cookie_name)
    path = request.url.path

    origin = request_origin(request)
    if origin is None:
        if session_token:
            _reject(request, "sin Origin ni Referer en una petición con cookie de sesión")
    elif origin not in settings.csrf_trusted_origin_list:
        _reject(request, f"origen no permitido: {origin}")

    if path in TOKEN_EXEMPT_PATHS:
        return

    is_session, expected = _session_csrf_claim(session_token)
    if not is_session:
        # Una cookie ausente, vencida o inválida no concede permisos: la ruta responderá 401 si exige sesión.
        return
    if expected is None:
        _reject(request, "la sesión no tiene token CSRF (emitida antes de activar la protección)")
    provided = request.headers.get(CSRF_HEADER_NAME, "")
    if not secrets.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
        _reject(request, "token CSRF ausente o incorrecto")


def _reject(request: Request, reason: str) -> NoReturn:
    logger.warning("CSRF rechazado: %s %s (%s)", request.method, request.url.path, reason)
    raise CsrfError(reason)
