from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.csrf import CSRF_HEADER_NAME
from app.main import app
from tests.conftest import API, DEFAULT_PASSWORD, TRUSTED_ORIGIN, consent_fields

FOREIGN_ORIGIN = "https://sitio-malicioso.example"
CSRF_FAILED = {
    "detail": "La solicitud fue rechazada por seguridad. Recarga la página e inténtalo de nuevo.",
    "code": "CSRF_FAILED",
}


def _session_cookie(client: TestClient) -> str:
    return client.cookies[settings.access_token_cookie_name]


def _update_nickname(client: TestClient, **kwargs) -> int:
    return client.patch(f"{API}/users/me", json={"nickname": "nuevo"}, **kwargs).status_code


def test_correct_token_is_accepted(user_client) -> None:
    client, _ = user_client("a")
    assert client.headers.get(CSRF_HEADER_NAME)
    assert _update_nickname(client) == 200


def test_missing_or_wrong_token_is_rejected(user_client) -> None:
    client, _ = user_client("a")
    token = client.headers.pop(CSRF_HEADER_NAME)

    missing = client.patch(f"{API}/users/me", json={"nickname": "nuevo"})
    assert missing.status_code == 403
    assert missing.json() == CSRF_FAILED

    assert _update_nickname(client, headers={CSRF_HEADER_NAME: token + "x"}) == 403
    # Bytes fuera de ASCII no deben provocar un 500 al comparar.
    assert _update_nickname(client, headers={CSRF_HEADER_NAME: "ñ-no-ascii".encode("utf-8")}) == 403


def test_foreign_origin_is_rejected_even_with_valid_token(user_client) -> None:
    client, _ = user_client("a")
    response = client.patch(f"{API}/users/me", json={"nickname": "nuevo"}, headers={"Origin": FOREIGN_ORIGIN})
    assert response.status_code == 403
    assert response.json()["code"] == "CSRF_FAILED"
    # "null" (iframes con sandbox, algunas redirecciones) tampoco es un origen de confianza.
    assert _update_nickname(client, headers={"Origin": "null"}) == 403


def test_referer_is_used_when_origin_is_missing(user_client) -> None:
    client, _ = user_client("a")
    client.headers.pop("Origin")

    assert _update_nickname(client, headers={"Referer": f"{TRUSTED_ORIGIN}/profile"}) == 200
    assert _update_nickname(client, headers={"Referer": f"{FOREIGN_ORIGIN}/ataque"}) == 403
    assert _update_nickname(client, headers={"Referer": "no-es-una-url"}) == 403


def test_without_origin_or_referer_only_cookie_requests_are_rejected(user_client, create_user) -> None:
    client, _ = user_client("a")
    client.headers.pop("Origin")
    assert _update_nickname(client) == 403

    # Un cliente sin cookie (curl, otra API) sigue funcionando sin Origin.
    create_user("curl@planati.com")
    anonymous = TestClient(app)
    try:
        response = anonymous.post(f"{API}/auth/login", json={"email": "curl@planati.com", "password": DEFAULT_PASSWORD})
    finally:
        anonymous.close()
    assert response.status_code == 200


def test_bearer_requests_are_exempt(user_client) -> None:
    client, _ = user_client("a")
    token = _session_cookie(client)
    bearer = TestClient(app, headers={"Authorization": f"Bearer {token}", "Origin": FOREIGN_ORIGIN})
    try:
        assert bearer.patch(f"{API}/users/me", json={"nickname": "bearer"}).status_code == 200
    finally:
        bearer.close()


def test_empty_bearer_does_not_skip_the_check(user_client) -> None:
    # Con "Bearer " vacío la autenticación cae a la cookie, así que el token CSRF sigue siendo obligatorio.
    client, _ = user_client("a")
    client.headers.pop(CSRF_HEADER_NAME)
    assert _update_nickname(client, headers={"Authorization": "Bearer "}) == 403


def test_safe_methods_are_not_affected(user_client) -> None:
    client, _ = user_client("a")
    client.headers.pop(CSRF_HEADER_NAME)
    assert client.get(f"{API}/users/me", headers={"Origin": FOREIGN_ORIGIN}).status_code == 200


def test_login_from_foreign_origin_is_rejected(make_client, create_user) -> None:
    create_user("victima@planati.com")
    client = make_client()
    response = client.post(
        f"{API}/auth/login",
        json={"email": "victima@planati.com", "password": DEFAULT_PASSWORD},
        headers={"Origin": FOREIGN_ORIGIN},
    )
    assert response.status_code == 403
    assert settings.access_token_cookie_name not in client.cookies


def test_session_routes_need_trusted_origin_but_no_token(make_client, create_user) -> None:
    create_user("login@planati.com")
    client = make_client()
    assert CSRF_HEADER_NAME not in client.headers
    login = client.post(f"{API}/auth/login", json={"email": "login@planati.com", "password": DEFAULT_PASSWORD})
    assert login.status_code == 200

    client.headers.pop(CSRF_HEADER_NAME)
    assert client.post(f"{API}/auth/logout", headers={"Origin": FOREIGN_ORIGIN}).status_code == 403
    assert client.post(f"{API}/auth/logout").status_code == 204


def test_token_changes_on_each_login(make_client, create_user) -> None:
    create_user("dos@planati.com")
    client = make_client()
    credentials = {"email": "dos@planati.com", "password": DEFAULT_PASSWORD}
    first = client.post(f"{API}/auth/login", json=credentials).json()["csrf_token"]
    second = client.post(f"{API}/auth/login", json=credentials).json()["csrf_token"]
    assert first != second

    # El token anterior deja de servir: la cookie vigente es la del segundo inicio de sesión.
    assert _update_nickname(client, headers={CSRF_HEADER_NAME: first}) == 403
    assert _update_nickname(client, headers={CSRF_HEADER_NAME: second}) == 200


def test_csrf_endpoint_returns_session_token(user_client, make_client) -> None:
    client, _ = user_client("a")
    response = client.get(f"{API}/auth/csrf")
    assert response.status_code == 200
    assert response.json() == {"csrf_token": client.headers[CSRF_HEADER_NAME]}
    assert response.headers["cache-control"] == "no-store"

    assert make_client().get(f"{API}/auth/csrf").status_code == 401


def test_registration_responses_include_token(make_client, register_restaurant) -> None:
    _, data = register_restaurant("a")
    assert isinstance(data["csrf_token"], str) and data["csrf_token"]

    client = make_client()
    response = client.post(
        f"{API}/auth/register",
        json={
            "full_name": "Persona Nueva",
            "email": "nueva@planati.com",
            "password": DEFAULT_PASSWORD,
            "phone_number": "3001234567",
            **consent_fields(),
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["csrf_token"] == client.get(f"{API}/auth/csrf").json()["csrf_token"]


def test_invalid_session_cookie_gets_401_not_csrf_error(make_client) -> None:
    client = make_client()
    client.cookies.set(settings.access_token_cookie_name, "no-es-un-jwt")
    response = client.post(f"{API}/users/me/upload-url")
    assert response.status_code == 401
