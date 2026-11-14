from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _normalize_origin(origin: str) -> str:
    return origin.strip().rstrip("/").lower()


class Settings(BaseSettings):
    app_name: str = "PlanATi API"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    secret_key: str = "development-secret"
    jwt_expiration_minutes: int = 60
    access_token_cookie_name: str = "access_token"
    access_token_cookie_path: str = "/"
    access_token_cookie_max_age_seconds: int = 3600
    access_token_cookie_samesite: str = "lax"
    # En producción se fuerza a True (ver session_cookie_params).
    access_token_cookie_secure: bool = False
    # Solo si la API va en otro subdominio que el frontend (decisión D12). Vacío = sin atributo Domain.
    access_token_cookie_domain: str = ""
    oauth_code_ttl_seconds: int = 120
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    frontend_url: str = "http://localhost:3000"
    sms_provider: str = "mock"
    otp_expiration_seconds: int = 300
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 60
    cors_origins: str = "http://localhost:3000"
    # Vacío = CORS_ORIGINS + FRONTEND_URL.
    csrf_trusted_origins: str = ""
    # None = activo en desarrollo y desactivado en producción.
    enable_api_docs: bool | None = None
    database_url: str = "postgresql+asyncpg://planati:planati@localhost:5432/planati"
    r2_endpoint_url: str = "https://<account-id>.r2.cloudflarestorage.com"
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = "planati-images"
    r2_public_base_url: str = "https://pub-<hash>.r2.dev"

    # Zona horaria de la aplicación: única fuente para convertir a hora local (ver app/core/time.py).
    app_timezone: str = "America/Bogota"

    # Geolocalización y mapa. Área de servicio: "sur,oeste,norte,este"; vacío = sin restricción.
    service_area_bounds: str = "-4.3,-81.8,13.6,-66.8"
    nearby_max_radius_km: float = 50
    map_max_markers: int = 500

    # Puntuación y posicionamiento (puntuación bayesiana).
    ranking_min_reviews: int = 5
    ranking_prior_mean: float = 3.5
    relevance_rating_weight: float = 0.6

    # Reseñas, reportes y moderación.
    review_max_images: int = 5
    review_comment_max_length: int = 2000
    reviews_per_day_limit: int = 10
    reports_per_day_limit: int = 20
    report_auto_hide_threshold: int = 0

    # Planes y recordatorios.
    reminders_enabled: bool = True
    reminder_poll_seconds: int = 60
    plan_min_lead_minutes: int = 15
    plan_max_days_ahead: int = 365
    plan_max_active: int = 50
    plan_complete_after_hours: int = 3
    plan_default_duration_minutes: int = 120
    notifications_retention_days: int = 90

    # Privacidad y datos personales (Ley 1581 de 2012).
    privacy_policy_version: str = "2026-11-01"
    terms_version: str = "2026-11-01"
    data_export_cooldown_minutes: int = 60

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("enable_api_docs", mode="before")
    @classmethod
    def _empty_docs_flag_as_default(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("service_area_bounds")
    @classmethod
    def _check_service_area_bounds(cls, value: str) -> str:
        if not value.strip():
            return ""
        parts = [part.strip() for part in value.split(",")]
        try:
            south, west, north, east = (float(part) for part in parts)
        except ValueError as error:
            raise ValueError("SERVICE_AREA_BOUNDS debe tener el formato sur,oeste,norte,este") from error
        if not (-90 <= south < north <= 90 and -180 <= west < east <= 180):
            raise ValueError("SERVICE_AREA_BOUNDS no describe un área válida (sur < norte y oeste < este)")
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env.strip().lower() == "production"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def csrf_trusted_origin_list(self) -> list[str]:
        raw = self.csrf_trusted_origins.strip()
        origins = raw.split(",") if raw else [*self.cors_origin_list, self.frontend_url]
        normalized = [_normalize_origin(origin) for origin in origins if origin.strip()]
        return list(dict.fromkeys(normalized))

    @property
    def service_area(self) -> tuple[float, float, float, float] | None:
        """(sur, oeste, norte, este) o None si no hay restricción de área."""
        if not self.service_area_bounds:
            return None
        south, west, north, east = (float(part) for part in self.service_area_bounds.split(","))
        return south, west, north, east

    @property
    def api_docs_enabled(self) -> bool:
        if self.enable_api_docs is not None:
            return self.enable_api_docs
        return not self.is_production


@lru_cache
def get_settings() -> Settings:
    return Settings()


# GUIA #10 TEMA: Subalgoritmos (funciones, procedimientos y modularización) -> variable global de solo lectura: la configuración se crea una vez y solo se lee.
settings = get_settings()
