"""Privacidad y datos personales (fase B8, Ley 1581): consentimientos, exportación y eliminación."""

import asyncio

import pytest
from sqlalchemy import func, select

from app.core.config import settings
from app.models.favorite import Favorite
from app.models.notification import Notification
from app.models.plan import Plan
from app.models.privacy import Consent
from app.models.report import Report
from app.models.review import Review
from app.models.user import User
from app.services import phone_verification_service
from tests.conftest import API, DEFAULT_PASSWORD, consent_fields, login, restaurant_payload
from tests.moderation_helpers import actions, detail, post_review
from tests.plan_helpers import create_plan


def register_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "full_name": "Persona Nueva",
        "email": "nueva@planati.com",
        "password": DEFAULT_PASSWORD,
        "phone_number": "3001234567",
        **consent_fields(),
    }
    body.update(overrides)
    return {key: value for key, value in body.items() if value is not None}


def consents_of(db_session, user_id: int) -> list[Consent]:
    async def scenario() -> list[Consent]:
        async with db_session() as session:
            return list((await session.scalars(select(Consent).where(Consent.user_id == user_id).order_by(Consent.id))).all())

    return asyncio.run(scenario())


def get_user(db_session, user_id: int) -> User:
    async def scenario() -> User:
        async with db_session() as session:
            return await session.get(User, user_id)

    return asyncio.run(scenario())


def count(db_session, model, *conditions) -> int:
    async def scenario() -> int:
        async with db_session() as session:
            return int(await session.scalar(select(func.count()).select_from(model).where(*conditions)) or 0)

    return asyncio.run(scenario())


@pytest.fixture
def sent_codes(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    sent: list[tuple[str, str]] = []

    class FakeSmsProvider:
        async def send_verification_code(self, phone_number: str, code: str) -> None:
            sent.append((phone_number, code))

    monkeypatch.setattr(phone_verification_service, "get_sms_provider", lambda _: FakeSmsProvider())
    monkeypatch.setattr(phone_verification_service.settings, "otp_resend_cooldown_seconds", 0)
    return sent


# --- Versiones y aceptación -------------------------------------------------------------------


def test_legal_versions_are_public(make_client) -> None:
    response = make_client().get(f"{API}/legal/versions")
    assert response.status_code == 200
    assert response.json() == {"privacy_policy": settings.privacy_policy_version, "terms": settings.terms_version}


@pytest.mark.parametrize(
    "overrides",
    [
        {"accept_privacy_policy": None},
        {"accept_terms": None},
        {"accept_privacy_policy": False},
        {"accept_terms": False},
        {"privacy_policy_version": None},
        {"terms_version": None},
    ],
)
def test_register_requires_acceptance(make_client, sent_codes, overrides) -> None:
    response = make_client().post(f"{API}/auth/register", json=register_body(**overrides))
    assert response.status_code == 422, response.text


def test_register_with_outdated_version_is_409(make_client, sent_codes, db_session) -> None:
    response = make_client().post(f"{API}/auth/register", json=register_body(terms_version="2020-01-01"))
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "CONSENT_VERSION_OUTDATED"
    assert body["current_versions"] == {"privacy_policy": settings.privacy_policy_version, "terms": settings.terms_version}
    assert count(db_session, User) == 0


def test_register_stores_consents_without_age_requirement(make_client, sent_codes, db_session) -> None:
    client = make_client()
    # No hay casilla de mayoría de edad (D10): basta con aceptar el tratamiento de datos y los términos.
    response = client.post(f"{API}/auth/register", json=register_body(), headers={"User-Agent": "pytest-navegador"})
    assert response.status_code == 201, response.text
    me = client.get(f"{API}/users/me").json()
    assert me["pending_consents"] == []

    rows = consents_of(db_session, me["id"])
    assert {(row.document, row.version, row.channel) for row in rows} == {
        ("PRIVACY_POLICY", settings.privacy_policy_version, "WEB_REGISTER"),
        ("TERMS", settings.terms_version, "WEB_REGISTER"),
    }
    assert all(row.user_agent == "pytest-navegador" and row.ip_address for row in rows)
    history = client.get(f"{API}/users/me/consents").json()
    assert {item["channel"] for item in history} == {"WEB_REGISTER"} and len(history) == 2


def test_restaurant_register_requires_and_stores_consents(make_client, db_session) -> None:
    payload = restaurant_payload("a")
    del payload["accept_terms"]
    assert make_client().post(f"{API}/auth/restaurant/register", json=payload).status_code == 422

    response = make_client().post(f"{API}/auth/restaurant/register", json=restaurant_payload("a"))
    assert response.status_code == 201, response.text
    rows = consents_of(db_session, response.json()["user_id"])
    assert {row.channel for row in rows} == {"RESTAURANT_REGISTER"} and len(rows) == 2


def test_outdated_account_must_accept_before_protected_routes(make_client, create_user, db_session) -> None:
    user_id = create_user("vieja@planati.com", phone_number="+573001110000", privacy_policy_version=None, terms_version="2020-01-01")
    client = make_client()
    login(client, "vieja@planati.com")

    me = client.get(f"{API}/users/me")
    assert me.status_code == 200
    assert me.json()["pending_consents"] == ["PRIVACY_POLICY", "TERMS"]
    for method, path in (("get", "/plans"), ("get", "/favorites"), ("put", "/favorites/1")):
        response = getattr(client, method)(f"{API}{path}")
        assert response.status_code == 403, (path, response.text)
        assert response.json()["code"] == "CONSENT_REQUIRED"
        assert response.json()["pending_consents"] == ["PRIVACY_POLICY", "TERMS"]
    # Sin aceptar puede ver sus notificaciones y descargar sus datos.
    assert client.get(f"{API}/notifications/unread-count").status_code == 200

    stale = client.post(f"{API}/users/me/consents", json={"privacy_policy_version": "2020-01-01", "terms_version": settings.terms_version})
    assert stale.status_code == 409 and stale.json()["code"] == "CONSENT_VERSION_OUTDATED"

    current = {"privacy_policy_version": settings.privacy_policy_version, "terms_version": settings.terms_version}
    accepted = client.post(f"{API}/users/me/consents", json=current)
    assert accepted.status_code == 200 and accepted.json()["pending_consents"] == []
    assert client.get(f"{API}/plans").status_code == 200
    # Idempotente: aceptar otra vez no duplica el historial.
    assert client.post(f"{API}/users/me/consents", json=current).status_code == 200
    rows = consents_of(db_session, user_id)
    assert len(rows) == 2 and {row.channel for row in rows} == {"RE_ACCEPTANCE"}


def test_google_account_accepts_on_complete_profile(make_client, create_user, db_session) -> None:
    user_id = create_user("google@planati.com", google_sub="sub-123", privacy_policy_version=None, terms_version=None)
    client = make_client()
    login(client, "google@planati.com")
    current = {"privacy_policy_version": settings.privacy_policy_version, "terms_version": settings.terms_version}
    assert client.post(f"{API}/users/me/consents", json=current).status_code == 200
    assert {row.channel for row in consents_of(db_session, user_id)} == {"GOOGLE_COMPLETE_PROFILE"}


def test_admin_and_restaurant_routes_require_consents(make_client, create_user, register_restaurant, db_session) -> None:
    create_user("admin-viejo@planati.com", role="admin", privacy_policy_version=None)
    admin = make_client()
    login(admin, "admin-viejo@planati.com")
    response = admin.get(f"{API}/admin/users")
    assert response.status_code == 403 and response.json()["code"] == "CONSENT_REQUIRED"

    owner, data = register_restaurant("a")
    assert owner.get(f"{API}/restaurant/profile").status_code == 200

    async def outdate() -> None:
        async with db_session() as session:
            user = await session.get(User, data["user_id"])
            user.terms_version = "2020-01-01"
            await session.commit()

    asyncio.run(outdate())
    response = owner.get(f"{API}/restaurant/profile")
    assert response.status_code == 403 and response.json()["pending_consents"] == ["TERMS"]


# --- Exportación ------------------------------------------------------------------------------


def test_export_contains_only_own_data_and_is_rate_limited(approved_restaurant, user_client, admin_client) -> None:
    _, establishment_id = approved_restaurant("a")
    client, user_id = user_client("a")
    other, _ = user_client("b")
    review = post_review(client, establishment_id, rating=2, comment="Comentario original del titular")
    post_review(other, establishment_id, rating=5, comment="Reseña de otra persona")
    blocked = admin_client.post(
        f"{API}/admin/reviews/{review['id']}/block-comment", json={"category": "OFFENSIVE_LANGUAGE"}
    )
    assert blocked.status_code == 200
    create_plan(client, establishment_id, notes="Cumpleaños")
    assert client.put(f"{API}/favorites/{establishment_id}").status_code == 204

    response = client.get(f"{API}/users/me/export")
    assert response.status_code == 200, response.text
    assert response.headers["content-disposition"] == 'attachment; filename="mis-datos-planati.json"'
    data = response.json()
    assert data["profile"]["id"] == user_id and data["profile"]["email"] == "usuario-a@planati.com"
    [exported] = data["reviews"]
    # Texto original aunque esté bloqueado.
    assert exported["comment"] == "Comentario original del titular" and exported["comment_status"] == "BLOCKED"
    assert [plan["notes"] for plan in data["plans"]] == ["Cumpleaños"]
    assert [fav["establishment_id"] for fav in data["favorites"]] == [establishment_id]
    assert any(n["type"] == "CONTENT_MODERATED" for n in data["notifications_last_90_days"])
    assert "Reseña de otra persona" not in response.text and "usuario-b" not in response.text

    again = client.get(f"{API}/users/me/export")
    assert again.status_code == 429 and again.json()["retry_after_seconds"] > 0


# --- Eliminación de la cuenta -----------------------------------------------------------------


def test_delete_account_with_password(
    approved_restaurant, user_client, admin_client, make_client, db_session
) -> None:
    _, establishment_id = approved_restaurant("a")
    client, user_id = user_client("a")
    other, other_id = user_client("b")
    review = post_review(client, establishment_id, rating=1, comment="Texto personal que debe desaparecer")
    post_review(other, establishment_id, rating=5)
    assert detail(make_client(), establishment_id)["rating_avg"] == 3.0
    admin_client.post(f"{API}/admin/reviews/{review['id']}/block-comment", json={"category": "OFFENSIVE_LANGUAGE"})
    create_plan(client, establishment_id)
    client.put(f"{API}/favorites/{establishment_id}")
    # Otro usuario reporta la reseña; el titular reporta la de otro.
    assert other.post(f"{API}/reports", json={"target_type": "REVIEW", "target_id": review["id"], "reason": "OFFENSIVE"}).status_code == 201
    other_review_id = other.get(f"{API}/reviews/me").json()["items"][0]["id"]
    assert client.post(f"{API}/reports", json={"target_type": "REVIEW", "target_id": other_review_id, "reason": "SPAM"}).status_code == 201

    async def add_consent() -> None:
        async with db_session() as session:
            session.add(Consent(user_id=user_id, document="TERMS", version=settings.terms_version,
                                channel="WEB_REGISTER", ip_address="10.0.0.1", user_agent="navegador"))
            await session.commit()

    asyncio.run(add_consent())
    old_cookie = client.cookies.get(settings.access_token_cookie_name)
    assert client.request("DELETE", f"{API}/users/me", json={"confirmation": "ELIMINAR", "password": "otra"}).status_code == 400
    assert client.request("DELETE", f"{API}/users/me", json={"confirmation": "eliminar", "password": DEFAULT_PASSWORD}).status_code == 422
    both = {"confirmation": "ELIMINAR", "password": DEFAULT_PASSWORD, "code": "123456"}
    assert client.request("DELETE", f"{API}/users/me", json=both).status_code == 422

    response = client.request("DELETE", f"{API}/users/me", json={"confirmation": "ELIMINAR", "password": DEFAULT_PASSWORD})
    assert response.status_code == 204, response.text
    assert settings.access_token_cookie_name in response.headers.get("set-cookie", "")

    # La sesión anterior ya no sirve y no se puede volver a entrar.
    stale = make_client()
    stale.cookies.set(settings.access_token_cookie_name, old_cookie)
    assert stale.get(f"{API}/users/me").status_code == 401
    assert make_client().post(f"{API}/auth/login", json={"email": "usuario-a@planati.com", "password": DEFAULT_PASSWORD}).status_code == 401

    # Contenido borrado y promedio recalculado.
    assert count(db_session, Review, Review.user_id == user_id) == 0
    assert count(db_session, Plan, Plan.user_id == user_id) == 0
    assert count(db_session, Favorite, Favorite.user_id == user_id) == 0
    assert count(db_session, Notification, Notification.user_id == user_id) == 0
    public = detail(make_client(), establishment_id)
    assert public["rating_avg"] == 5.0 and public["rating_count"] == 1

    # Lápida anonimizada.
    tombstone = get_user(db_session, user_id)
    assert tombstone.status == "DELETED" and tombstone.deleted_at is not None
    assert tombstone.full_name == "Usuario eliminado" and tombstone.nickname is None
    assert tombstone.email.endswith("@eliminado.planati.invalid") and tombstone.phone_number is None

    # Trazabilidad: consentimientos sin IP ni user agent, bitácora sin el texto, reportes cerrados o conservados.
    rows = consents_of(db_session, user_id)
    assert len(rows) == 1 and rows[0].ip_address is None and rows[0].user_agent is None
    [block] = actions(db_session, action="BLOCK_COMMENT", target_id=review["id"])
    assert block.details["redacted"] == "ACCOUNT_DELETED" and "comment" not in block.details
    assert block.details["category"] == "OFFENSIVE_LANGUAGE"
    [deleted] = actions(db_session, action="DELETE_ACCOUNT", target_id=user_id)
    assert deleted.admin_id is None and deleted.details["reviews"] == 1 and deleted.details["plans"] == 1

    async def reports() -> tuple[Report, Report]:
        async with db_session() as session:
            on_review = await session.scalar(select(Report).where(Report.target_id == review["id"]))
            by_user = await session.scalar(select(Report).where(Report.reporter_id == user_id))
            return on_review, by_user

    on_review, by_user = asyncio.run(reports())
    assert on_review.status == "RESOLVED" and "eliminó la cuenta" in on_review.resolution_note
    assert by_user is not None and by_user.status == "OPEN"
    assert deleted.details["report_ids"] == [on_review.id]

    # El admin no ve la lápida en la lista general ni puede actuar sobre ella.
    listed = admin_client.get(f"{API}/admin/users").json()["items"]
    assert user_id not in [item["id"] for item in listed] and other_id in [item["id"] for item in listed]
    assert admin_client.get(f"{API}/admin/users", params={"status": "DELETED"}).json()["total"] == 1
    assert admin_client.post(f"{API}/admin/users/{user_id}/suspend", json={"reason": "Prueba"}).status_code == 409



def test_deleted_account_email_and_phone_can_register_again(user_client, make_client, sent_codes, db_session) -> None:
    client, user_id = user_client("a")
    phone = client.get(f"{API}/users/me").json()["phone_number"]
    assert client.request("DELETE", f"{API}/users/me", json={"confirmation": "ELIMINAR", "password": DEFAULT_PASSWORD}).status_code == 204
    response = make_client().post(
        f"{API}/auth/register", json=register_body(email="usuario-a@planati.com", phone_number=phone.replace("+57", ""))
    )
    assert response.status_code == 201, response.text


def test_delete_account_with_sms_code(user_client, sent_codes) -> None:
    client, _ = user_client("a")
    phone = client.get(f"{API}/users/me").json()["phone_number"]
    assert client.post(f"{API}/users/me/delete/send-code").status_code == 200
    [(sent_to, code)] = sent_codes
    assert sent_to == phone
    wrong = "000000" if code != "000000" else "111111"
    assert client.request("DELETE", f"{API}/users/me", json={"confirmation": "ELIMINAR", "code": wrong}).status_code == 400
    response = client.request("DELETE", f"{API}/users/me", json={"confirmation": "ELIMINAR", "code": code})
    assert response.status_code == 204, response.text
    assert client.get(f"{API}/users/me").status_code == 401


def test_phone_verification_code_cannot_delete_account(user_client, sent_codes) -> None:
    client, _ = user_client("a")
    # Un código de cambio de teléfono no sirve para confirmar la eliminación.
    assert client.post(f"{API}/users/me/phone/send-code", json={"phone_number": "3209998877"}).status_code == 200
    [(_, code)] = sent_codes
    response = client.request("DELETE", f"{API}/users/me", json={"confirmation": "ELIMINAR", "code": code})
    assert response.status_code == 400


def test_restaurant_and_admin_cannot_self_delete(register_restaurant, admin_client, sent_codes) -> None:
    owner, _ = register_restaurant("a")
    body = {"confirmation": "ELIMINAR", "password": DEFAULT_PASSWORD}
    for client in (owner, admin_client):
        response = client.request("DELETE", f"{API}/users/me", json=body)
        assert response.status_code == 409 and response.json()["code"] == "SUPPORT_REQUIRED"
        assert client.post(f"{API}/users/me/delete/send-code").status_code == 409
        assert client.get(f"{API}/users/me").status_code == 200
    assert sent_codes == []
