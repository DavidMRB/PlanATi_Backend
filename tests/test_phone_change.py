import pytest

from app.services import phone_verification_service
from tests.conftest import API, DEFAULT_PASSWORD

OLD_PHONE = "+573001112233"
NEW_PHONE = "+573104445566"


@pytest.fixture
def sent_codes(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    sent: list[tuple[str, str]] = []

    class FakeSmsProvider:
        async def send_verification_code(self, phone_number: str, code: str) -> None:
            sent.append((phone_number, code))

    monkeypatch.setattr(phone_verification_service, "get_sms_provider", lambda _: FakeSmsProvider())
    monkeypatch.setattr(phone_verification_service.settings, "otp_resend_cooldown_seconds", 0)
    return sent


@pytest.fixture
def user_client(make_client, create_user):
    create_user("user@planati.com")
    client = make_client()
    client.post(f"{API}/auth/login", json={"email": "user@planati.com", "password": DEFAULT_PASSWORD})
    return client


def _verify_initial_phone(client, sent_codes) -> None:
    assert client.post(f"{API}/users/me/phone/send-code", json={"phone_number": OLD_PHONE}).status_code == 200
    code = sent_codes[-1][1]
    response = client.post(f"{API}/users/me/phone/verify", json={"phone_number": OLD_PHONE, "code": code})
    assert response.status_code == 200, response.text
    assert response.json()["phone_number"] == OLD_PHONE


def test_phone_change_keeps_old_number_until_verified(user_client, sent_codes) -> None:
    _verify_initial_phone(user_client, sent_codes)

    # Cambiarlo directamente por PATCH no está permitido y no altera nada.
    direct = user_client.patch(f"{API}/users/me", json={"phone_number": NEW_PHONE, "nickname": "Cambio"})
    assert direct.status_code == 400
    me = user_client.get(f"{API}/users/me").json()
    assert me["phone_number"] == OLD_PHONE
    assert me["nickname"] != "Cambio"

    # Pedir el código no toca la cuenta: sigue verificada, activa y con el número anterior.
    assert user_client.post(f"{API}/users/me/phone/send-code", json={"phone_number": NEW_PHONE}).status_code == 200
    me = user_client.get(f"{API}/users/me").json()
    assert me["phone_number"] == OLD_PHONE
    assert me["phone_verified"] is True
    assert me["status"] == "ACTIVE"

    wrong = user_client.post(f"{API}/users/me/phone/verify", json={"phone_number": NEW_PHONE, "code": "000000"})
    assert wrong.status_code == 400
    assert user_client.get(f"{API}/users/me").json()["phone_number"] == OLD_PHONE

    code = sent_codes[-1][1]
    ok = user_client.post(f"{API}/users/me/phone/verify", json={"phone_number": NEW_PHONE, "code": code})
    assert ok.status_code == 200
    body = ok.json()
    assert body["phone_number"] == NEW_PHONE
    assert body["phone_verified"] is True
    assert body["status"] == "ACTIVE"


def test_patch_with_same_phone_and_picture_still_works(user_client, sent_codes) -> None:
    _verify_initial_phone(user_client, sent_codes)
    response = user_client.patch(
        f"{API}/users/me",
        json={"phone_number": OLD_PHONE, "nickname": "Nuevo apodo", "picture": "https://pub.r2.dev/avatars/a.png"},
    )
    assert response.status_code == 200
    assert response.json()["nickname"] == "Nuevo apodo"
    assert response.json()["picture"] == "https://pub.r2.dev/avatars/a.png"


def test_phone_change_rejects_current_and_foreign_numbers(make_client, user_client, create_user, sent_codes) -> None:
    _verify_initial_phone(user_client, sent_codes)
    same = user_client.post(f"{API}/users/me/phone/send-code", json={"phone_number": OLD_PHONE})
    assert same.status_code == 400

    create_user("other@planati.com")
    other = make_client()
    other.post(f"{API}/auth/login", json={"email": "other@planati.com", "password": DEFAULT_PASSWORD})
    taken = other.post(f"{API}/users/me/phone/send-code", json={"phone_number": OLD_PHONE})
    assert taken.status_code == 400
