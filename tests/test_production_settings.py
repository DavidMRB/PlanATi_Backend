import pytest

from app.core.config import Settings
from app.core.startup_checks import InsecureSettingsError, enforce_settings, validate_settings

STRONG_SECRET = "Xk3v9Q2mL7pR4sT8wZ1yB6nC0dF5gH2jK9lM3qW7eR4tY8uI1oP6aS0dF5gH"

SAFE_PRODUCTION = {
    "app_env": "production",
    "secret_key": STRONG_SECRET,
    "access_token_cookie_secure": True,
    "access_token_cookie_samesite": "lax",
    "frontend_url": "https://planati.example",
    "cors_origins": "https://planati.example",
    "csrf_trusted_origins": "",
    "google_redirect_uri": "https://planati.example/api/v1/auth/google/callback",
    "sms_provider": "twilio",
    "database_url": "postgresql+asyncpg://planati_app:clave-segura@db.interna:5432/planati",
    "r2_endpoint_url": "https://cuenta.r2.cloudflarestorage.com",
    "r2_access_key_id": "clave-de-acceso",
    "r2_secret_access_key": "secreto-de-acceso",
    "r2_public_base_url": "https://pub-123abc.r2.dev",
    "enable_api_docs": None,
}


def make_settings(**overrides: object) -> Settings:
    # _env_file=None: la prueba no debe depender del .env local.
    return Settings(_env_file=None, **(SAFE_PRODUCTION | overrides))


def problems_for(**overrides: object) -> list[str]:
    return validate_settings(make_settings(**overrides))


def test_safe_production_settings_have_no_problems() -> None:
    assert problems_for() == []
    enforce_settings(make_settings())  # no lanza


@pytest.mark.parametrize(
    "secret",
    ["development-secret", "replace-with-a-local-secret", "change-me", "corta-123", "a" * 64],
)
def test_weak_secret_key_is_rejected(secret: str) -> None:
    assert any("SECRET_KEY" in problem for problem in problems_for(secret_key=secret))


def test_cookie_is_forced_secure_in_production() -> None:
    # ACCESS_TOKEN_COOKIE_SECURE=false se ignora en producción, así que no es un problema...
    assert problems_for(access_token_cookie_secure=False) == []
    # ...pero un SameSite inválido sí.
    assert any("SAMESITE" in problem for problem in problems_for(access_token_cookie_samesite="laxo"))


def test_cookie_rule_reports_insecure_cookie_outside_forced_mode() -> None:
    problems = validate_settings(make_settings(app_env="staging", access_token_cookie_secure=False, access_token_cookie_samesite="none"))
    assert any("Secure" in problem and "SameSite=None" in problem for problem in problems)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("frontend_url", "http://planati.example"),
        ("frontend_url", "https://localhost:3000"),
        ("cors_origins", "https://planati.example,http://localhost:3000"),
        ("cors_origins", "*"),
        ("google_redirect_uri", "http://planati.example/api/v1/auth/google/callback"),
        ("csrf_trusted_origins", "https://127.0.0.1:3000"),
    ],
)
def test_urls_must_be_https_and_public(field: str, value: str) -> None:
    assert problems_for(**{field: value}), f"{field}={value} debería rechazarse"


def test_mock_sms_provider_is_rejected() -> None:
    assert any("SMS_PROVIDER" in problem for problem in problems_for(sms_provider="mock"))


def test_development_database_credentials_are_rejected() -> None:
    problems = problems_for(database_url="postgresql+asyncpg://planati:planati@db:5432/planati")
    assert any("planati/planati" in problem for problem in problems)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("r2_endpoint_url", "https://<account-id>.r2.cloudflarestorage.com"),
        ("r2_access_key_id", "replace-with-r2-access-key"),
        ("r2_secret_access_key", "replace-with-r2-secret-key"),
        ("r2_public_base_url", "https://pub-<hash>.r2.dev"),
    ],
)
def test_r2_placeholders_are_rejected(field: str, value: str) -> None:
    assert any(field.upper() in problem for problem in problems_for(**{field: value}))


def test_enforce_settings_blocks_startup_and_lists_every_problem() -> None:
    insecure = make_settings(secret_key="development-secret", sms_provider="mock")
    with pytest.raises(InsecureSettingsError) as error:
        enforce_settings(insecure)
    assert len(error.value.problems) == 2
    assert "SECRET_KEY" in str(error.value) and "SMS_PROVIDER" in str(error.value)


def test_development_does_not_block_startup() -> None:
    enforce_settings(make_settings(app_env="development", secret_key="development-secret", sms_provider="mock"))


def test_api_docs_are_disabled_in_production_unless_enabled() -> None:
    assert make_settings().api_docs_enabled is False
    assert make_settings(enable_api_docs="").api_docs_enabled is False
    assert make_settings(enable_api_docs=True).api_docs_enabled is True
    assert make_settings(app_env="development").api_docs_enabled is True
    assert make_settings(app_env="development", enable_api_docs=False).api_docs_enabled is False


def test_csrf_trusted_origins_default_to_cors_and_frontend() -> None:
    cfg = make_settings(cors_origins="https://planati.example/, https://admin.planati.example", frontend_url="https://planati.example")
    assert cfg.csrf_trusted_origin_list == ["https://planati.example", "https://admin.planati.example"]
    assert make_settings(csrf_trusted_origins="https://Otro.example").csrf_trusted_origin_list == ["https://otro.example"]


def test_service_area_bounds() -> None:
    assert make_settings().service_area == (-4.3, -81.8, 13.6, -66.8)
    assert make_settings(service_area_bounds="").service_area is None
    with pytest.raises(ValueError):
        make_settings(service_area_bounds="13.6,-81.8,-4.3,-66.8")  # sur > norte
    with pytest.raises(ValueError):
        make_settings(service_area_bounds="uno,dos,tres")
