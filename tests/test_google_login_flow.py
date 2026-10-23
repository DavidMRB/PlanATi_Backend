from urllib.parse import parse_qs, urlparse

import pytest

from app.api.routes import auth as auth_routes
from tests.conftest import API

GOOGLE_PICTURE = "https://lh3.googleusercontent.com/a/foto-de-google=s96-c"
IDENTITY = {
    "google_sub": "sub-nuevo",
    "email": "nuevo@gmail.com",
    "email_verified": True,
    "name": "Persona Nueva",
    "picture": GOOGLE_PICTURE,
}


@pytest.fixture
def google_login(make_client, monkeypatch: pytest.MonkeyPatch):
    async def fake_authenticate_code(_code: str) -> dict:
        return IDENTITY

    monkeypatch.setattr(auth_routes.google_client, "authenticate_code", fake_authenticate_code)

    def login():
        client = make_client()
        client.get(f"{API}/auth/google")
        state = client.cookies.get("oauth_state")
        callback = client.get(
            f"{API}/auth/google/callback", params={"code": "codigo", "state": state}, follow_redirects=False
        )
        assert callback.status_code == 303, callback.text
        temp_code = parse_qs(urlparse(callback.headers["location"]).query)["code"][0]
        exchange = client.post(f"{API}/auth/google/exchange", json={"code": temp_code})
        assert exchange.status_code == 200, exchange.text
        return client, exchange.json()

    return login


def test_new_google_user_arrives_with_google_picture(google_login) -> None:
    client, exchange = google_login()
    assert exchange["registration_complete"] is False

    me = client.get(f"{API}/users/me").json()
    assert me["picture"] == GOOGLE_PICTURE


def test_removed_picture_comes_back_from_google_on_next_login(google_login) -> None:
    client, _ = google_login()
    assert client.patch(f"{API}/users/me", json={"picture": "https://pub.r2.dev/avatars/mia.png"}).status_code == 200

    # Con foto propia, un nuevo login con Google no la pisa.
    client, _ = google_login()
    assert client.get(f"{API}/users/me").json()["picture"] == "https://pub.r2.dev/avatars/mia.png"

    # Al quitarla (el frontend envía cadena vacía) queda sin foto...
    removed = client.patch(f"{API}/users/me", json={"picture": ""})
    assert removed.status_code == 200
    assert removed.json()["picture"] is None

    # ...y el siguiente login con Google la repone.
    client, _ = google_login()
    assert client.get(f"{API}/users/me").json()["picture"] == GOOGLE_PICTURE
