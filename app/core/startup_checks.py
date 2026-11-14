"""Validación de la configuración al arrancar (plan fase 2, sección 9.5).

Con `APP_ENV=production` la aplicación no arranca si encuentra una configuración insegura y lista
todos los problemas a la vez. En desarrollo solo se avisa de una clave secreta débil.
"""

import logging

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from app.core.config import Settings
from app.core.security import cookie_is_secure

logger = logging.getLogger(__name__)

DEFAULT_SECRET_KEYS = frozenset({"development-secret", "replace-with-a-local-secret", "change-me"})
MIN_SECRET_KEY_LENGTH = 43  # longitud de secrets.token_urlsafe(32)
VALID_SAMESITE_VALUES = frozenset({"lax", "strict", "none"})
LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0")


class InsecureSettingsError(RuntimeError):
    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        listado = "\n".join(f"  - {problem}" for problem in problems)
        super().__init__(f"Configuración insegura para producción:\n{listado}")


def secret_key_problem(secret_key: str) -> str | None:
    key = secret_key.strip()
    if key.lower() in DEFAULT_SECRET_KEYS:
        return "SECRET_KEY tiene un valor por defecto."
    if len(key) < MIN_SECRET_KEY_LENGTH:
        return f"SECRET_KEY es demasiado corta (mínimo {MIN_SECRET_KEY_LENGTH} caracteres)."
    if len(set(key)) == 1:
        return "SECRET_KEY está formada por un solo carácter repetido."
    return None


def _url_problem(name: str, url: str) -> str | None:
    value = url.strip().lower()
    if "*" in value:
        return f"{name} no puede contener '*'."
    if not value.startswith("https://"):
        return f"{name} debe usar https:// ({url})."
    if any(host in value for host in LOCAL_HOSTS):
        return f"{name} no puede apuntar a localhost ({url})."
    return None


def validate_settings(settings: Settings) -> list[str]:
    """Problemas que impedirían arrancar en producción (lista vacía = configuración aceptable)."""
    problems: list[str] = []

    if problem := secret_key_problem(settings.secret_key):
        problems.append(f"{problem} Genera una con: python -c \"import secrets; print(secrets.token_urlsafe(64))\"")

    samesite = settings.access_token_cookie_samesite.strip().lower()
    if samesite not in VALID_SAMESITE_VALUES:
        problems.append("ACCESS_TOKEN_COOKIE_SAMESITE debe ser lax, strict o none.")
    if not cookie_is_secure(settings):
        # En producción Secure se fuerza; la regla protege si alguien cambia ese comportamiento.
        message = "La cookie de sesión debe ser Secure."
        if samesite == "none":
            message += " SameSite=None exige Secure."
        problems.append(message)

    urls = [("FRONTEND_URL", settings.frontend_url), ("GOOGLE_REDIRECT_URI", settings.google_redirect_uri)]
    urls += [("CORS_ORIGINS", origin) for origin in settings.cors_origin_list]
    if settings.csrf_trusted_origins.strip():
        urls += [("CSRF_TRUSTED_ORIGINS", origin) for origin in settings.csrf_trusted_origin_list]
    if not settings.cors_origin_list:
        problems.append("CORS_ORIGINS no puede estar vacío.")
    for name, url in urls:
        if problem := _url_problem(name, url):
            problems.append(problem)

    if settings.sms_provider.strip().lower() == "mock":
        problems.append("SMS_PROVIDER=mock escribe los códigos OTP en los logs; configura un proveedor real.")

    try:
        database_url = make_url(settings.database_url)
    except ArgumentError:
        problems.append("DATABASE_URL no es una URL válida.")
    else:
        if database_url.username == "planati" and database_url.password == "planati":
            problems.append("DATABASE_URL usa las credenciales de desarrollo planati/planati.")

    r2_values = {
        "R2_ENDPOINT_URL": settings.r2_endpoint_url,
        "R2_ACCESS_KEY_ID": settings.r2_access_key_id,
        "R2_SECRET_ACCESS_KEY": settings.r2_secret_access_key,
        "R2_PUBLIC_BASE_URL": settings.r2_public_base_url,
    }
    # GUIA #6 TEMA: Ciclos -> recorre las variables de R2 y detecta marcadores sin reemplazar.
    for name, value in r2_values.items():
        if "<" in value or value.strip().lower().startswith("replace-with"):
            problems.append(f"{name} conserva el marcador de .env.example.")

    return problems


# GUIA #10 TEMA: Subalgoritmos (funciones, procedimientos y modularización) -> procedimiento (`-> None`): impide arrancar con una configuración insegura;
# en lugar de `print()` usa una excepción y el logging.
def enforce_settings(settings: Settings) -> None:
    """Se llama en el `lifespan`: en producción impide arrancar con una configuración insegura."""
    if settings.is_production:
        problems = validate_settings(settings)
        if problems:
            raise InsecureSettingsError(problems)
        return
    if problem := secret_key_problem(settings.secret_key):
        logger.warning("%s Usa una clave generada también en local (ver .env.example).", problem)
