from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "PlanATi API"
    app_env: str = "development"
    api_v1_prefix: str = "/api/v1"
    secret_key: str = "development-secret"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/api/v1/auth/google/callback"
    frontend_url: str = "http://localhost:3000"
    sms_provider: str = "mock"
    otp_expiration_seconds: int = 300
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 60
    cors_origins: str = "http://localhost:3000"
    database_url: str = "postgresql+asyncpg://planati:planati@localhost:5432/planati"
    r2_endpoint_url: str = "https://<account-id>.r2.cloudflarestorage.com"
    r2_access_key_id: str = ""
    r2_secret_access_key: str = ""
    r2_bucket_name: str = "planati-images"
    r2_public_base_url: str = "https://pub-<hash>.r2.dev"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
