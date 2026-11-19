from http.cookies import SimpleCookie

import pytest

from app.api.routes import auth as auth_routes
from app.core.config import settings
from tests.conftest import API, DEFAULT_PASSWORD


@pytest.fixture
def production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_env", "production")
    # Aunque alguien deje ACCESS_TOKEN_COOKIE_SECURE=false, en producción la cookie es Secure.
    monkeypatch.setattr(settings, "access_token_cookie_secure", False)


def _set_cookie(response, name: str) -> dict[str, str | bool]:
    for header in response.headers.get_list("set-cookie"):
        cookie = SimpleCookie()
        cookie.load(header)
        if name in cookie:
            morsel = cookie[name]
            return {key: morsel[key] for key in morsel.keys() if morsel[key] != ""} | {"value": morsel.value}
    raise AssertionError(f"La respuesta no fija la cookie {name}: {response.headers.get_list('set-cookie')}")


def test_session_cookie_is_secure_in_production(production, make_client, create_user) -> None:
    create_user("prod@planati.com")
    client = make_client()
    response = client.post(f"{API}/auth/login", json={"email": "prod@planati.com", "password": DEFAULT_PASSWORD})
    assert response.status_code == 200

    cookie = _set_cookie(response, settings.access_token_cookie_name)
    assert cookie["secure"] is True
    assert cookie["httponly"] is True
    assert cookie["samesite"].lower() == "lax"
    assert cookie["path"] == "/"


def test_logout_deletes_cookie_with_same_attributes(production, make_client) -> None:
    response = make_client().post(f"{API}/auth/logout")
    assert response.status_code == 204

    cookie = _set_cookie(response, settings.access_token_cookie_name)
    assert cookie["value"] == ""
    assert cookie["max-age"] == "0"
    assert cookie["secure"] is True
    assert cookie["httponly"] is True
    assert cookie["samesite"].lower() == "lax"
    assert cookie["path"] == "/"


def test_oauth_state_cookie_is_secure_in_production(production, make_client, monkeypatch) -> None:
    monkeypatch.setattr(auth_routes.google_client, "authorization_url", lambda state: f"https://accounts.google.com/?state={state}")
    response = make_client().get(f"{API}/auth/google")
    assert response.status_code == 200

    cookie = _set_cookie(response, "oauth_state")
    assert cookie["secure"] is True
    assert cookie["httponly"] is True
    assert cookie["samesite"].lower() == "lax"
    assert cookie["path"] == "/"


def test_development_cookie_works_over_http(make_client, create_user) -> None:
    create_user("dev@planati.com")
    response = make_client().post(f"{API}/auth/login", json={"email": "dev@planati.com", "password": DEFAULT_PASSWORD})
    cookie = _set_cookie(response, settings.access_token_cookie_name)
    assert "secure" not in cookie
    assert cookie["httponly"] is True


def test_cookie_domain_is_only_sent_when_configured(monkeypatch, make_client, create_user) -> None:
    monkeypatch.setattr(settings, "access_token_cookie_domain", "planati.example")
    create_user("dominio@planati.com")
    response = make_client().post(f"{API}/auth/login", json={"email": "dominio@planati.com", "password": DEFAULT_PASSWORD})
    assert _set_cookie(response, settings.access_token_cookie_name)["domain"] == "planati.example"
