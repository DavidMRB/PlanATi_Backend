"""B5: gestión de usuarios desde la consola admin y efecto de la suspensión en la sesión."""

import asyncio

import pytest

from app.models.user import User
from app.services import admin_service
from app.services.moderation_service import ModerationError
from tests.conftest import API, DEFAULT_PASSWORD, login
from tests.moderation_helpers import REASON, actions, notification_types, post_review


def test_list_users_is_paginated_with_filters_and_counts(admin_client, user_client, approved_restaurant) -> None:
    client_a, user_a = user_client("a")
    user_client("b")
    _, establishment_id = approved_restaurant("r")
    post_review(client_a, establishment_id, comment="Muy bueno")

    page = admin_client.get(f"{API}/admin/users", params={"limit": 2}).json()
    assert page["total"] == 4  # admin, dos usuarios y la cuenta del restaurante
    assert len(page["items"]) == 2 and page["limit"] == 2

    users = admin_client.get(f"{API}/admin/users", params={"role": "user"}).json()["items"]
    assert {item["email"] for item in users} == {"usuario-a@planati.com", "usuario-b@planati.com"}
    by_id = {item["id"]: item for item in users}
    assert by_id[user_a]["reviews_count"] == 1
    assert by_id[user_a]["open_reports_count"] == 0

    searched = admin_client.get(f"{API}/admin/users", params={"search": "usuarioa"}).json()["items"]
    assert [item["id"] for item in searched] == [user_a]

    restaurants = admin_client.get(f"{API}/admin/users", params={"role": "restaurant"}).json()["items"]
    assert restaurants[0]["establishment_id"] == establishment_id

    assert admin_client.get(f"{API}/admin/users", params={"status": "SUSPENDED"}).json()["total"] == 0
    assert admin_client.get(f"{API}/admin/users", params={"status": "OTRO"}).status_code == 422


def test_user_detail(admin_client, user_client, approved_restaurant) -> None:
    client_a, user_a = user_client("a")
    _, establishment_id = approved_restaurant("r")
    post_review(client_a, establishment_id, comment="Muy bueno")
    admin_client.post(f"{API}/admin/users/{user_a}/notify", json={"title": "Hola", "body": "Gracias por participar"})

    body = admin_client.get(f"{API}/admin/users/{user_a}").json()
    assert body["email"] == "usuario-a@planati.com"
    assert body["reviews_count"] == 1
    assert [review["comment"] for review in body["recent_reviews"]] == ["Muy bueno"]
    assert body["recent_reviews"][0]["author"]["email"] == "usuario-a@planati.com"
    assert [entry["action"] for entry in body["moderation_history"]] == ["NOTIFY_USER"]
    assert body["establishments"] == []
    assert admin_client.get(f"{API}/admin/users/9999").status_code == 404


def test_change_role_with_protections(admin_client, user_client, register_restaurant, db_session) -> None:
    _, user_a = user_client("a")
    _, restaurant = register_restaurant("r")
    me = admin_client.get(f"{API}/users/me").json()

    promoted = admin_client.patch(f"{API}/admin/users/{user_a}/role", json={"role": "admin"})
    assert promoted.status_code == 200 and promoted.json()["role"] == "admin"
    assert admin_client.patch(f"{API}/admin/users/{user_a}/role", json={"role": "user"}).json()["role"] == "user"

    own = admin_client.patch(f"{API}/admin/users/{me['id']}/role", json={"role": "user"})
    assert own.status_code == 400
    assert admin_client.patch(f"{API}/admin/users/{restaurant['user_id']}/role", json={"role": "user"}).status_code == 400
    assert admin_client.patch(f"{API}/admin/users/{user_a}/role", json={"role": "restaurant"}).status_code == 400

    entries = actions(db_session, action="CHANGE_ROLE")
    assert [entry.details for entry in entries] == [
        {"before": "user", "after": "admin"},
        {"before": "admin", "after": "user"},
    ]


def test_last_active_admin_is_protected(db_session, create_user) -> None:
    """Defensa en profundidad: sin otro admin activo no se le quita el rol ni se suspende al último."""
    only_admin = create_user("unico@planati.com", role="admin")
    suspended_admin = create_user("suspendido@planati.com", role="admin", status="SUSPENDED")

    async def scenario() -> None:
        async with db_session() as session:
            target = await session.get(User, only_admin)
            actor = await session.get(User, suspended_admin)
            with pytest.raises(ModerationError, match="último administrador"):
                await admin_service.change_role(session, actor, target, "user")
            with pytest.raises(ModerationError, match="último administrador"):
                await admin_service.suspend_user(session, actor, target, REASON)

    asyncio.run(scenario())


def test_suspended_user_loses_session_and_cannot_log_in(admin_client, user_client) -> None:
    client_a, user_a = user_client("a")
    assert client_a.get(f"{API}/users/me").status_code == 200

    response = admin_client.post(f"{API}/admin/users/{user_a}/suspend", json={"reason": "Reseñas falsas repetidas"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "SUSPENDED" and body["suspension_reason"] == "Reseñas falsas repetidas"
    assert body["establishment_id"] is None

    # La cookie ya emitida deja de servir de inmediato.
    for method, path in [("get", "/users/me"), ("get", "/notifications/unread-count"), ("get", "/auth/csrf")]:
        blocked = getattr(client_a, method)(f"{API}{path}")
        assert blocked.status_code == 403, path
        assert blocked.json() == {
            "detail": "Tu cuenta está suspendida.",
            "code": "ACCOUNT_SUSPENDED",
            "reason": "Reseñas falsas repetidas",
        }
    assert client_a.post(f"{API}/auth/logout").status_code == 204

    relogin = client_a.post(f"{API}/auth/login", json={"email": "usuario-a@planati.com", "password": DEFAULT_PASSWORD})
    assert relogin.status_code == 403 and relogin.json()["code"] == "ACCOUNT_SUSPENDED"
    assert "set-cookie" not in relogin.headers
    # Con una contraseña incorrecta no se revela que la cuenta existe y está suspendida.
    wrong = client_a.post(f"{API}/auth/login", json={"email": "usuario-a@planati.com", "password": "Otra123!"})
    assert wrong.status_code == 401

    # Las páginas públicas siguen funcionando como visitante.
    assert client_a.get(f"{API}/establishments").status_code == 200

    assert admin_client.post(f"{API}/admin/users/{user_a}/suspend", json={"reason": "Otra vez"}).status_code == 409


def test_reactivate_user(admin_client, user_client, create_user, make_client) -> None:
    client_a, user_a = user_client("a")
    pending = create_user("sin-telefono@planati.com", phone_verified=False, status="PENDING_PHONE")
    for user_id in (user_a, pending):
        assert admin_client.post(f"{API}/admin/users/{user_id}/suspend", json={"reason": REASON}).status_code == 200

    reactivated = admin_client.post(f"{API}/admin/users/{user_a}/reactivate")
    assert reactivated.status_code == 200
    assert reactivated.json()["status"] == "ACTIVE" and reactivated.json()["suspension_reason"] is None
    pending_body = admin_client.post(f"{API}/admin/users/{pending}/reactivate", json={"note": "Apelación aceptada"}).json()
    assert pending_body["status"] == "PENDING_PHONE"
    assert admin_client.post(f"{API}/admin/users/{user_a}/reactivate").status_code == 409

    login(client_a, "usuario-a@planati.com")
    assert notification_types(client_a)[:2] == ["ACCOUNT_REACTIVATED", "ACCOUNT_SUSPENDED"]


def test_admin_cannot_suspend_self(admin_client) -> None:
    me = admin_client.get(f"{API}/users/me").json()
    response = admin_client.post(f"{API}/admin/users/{me['id']}/suspend", json={"reason": REASON})
    assert response.status_code == 400
    assert admin_client.get(f"{API}/users/me").status_code == 200


def test_suspending_restaurant_account_returns_establishment(admin_client, approved_restaurant) -> None:
    restaurant_client, establishment_id = approved_restaurant("r")
    owner_id = restaurant_client.get(f"{API}/users/me").json()["id"]
    body = admin_client.post(f"{API}/admin/users/{owner_id}/suspend", json={"reason": REASON}).json()
    assert body["establishment_id"] == establishment_id
    assert restaurant_client.get(f"{API}/restaurant/status").json()["code"] == "ACCOUNT_SUSPENDED"


def test_suspend_validation(admin_client, user_client) -> None:
    _, user_a = user_client("a")
    assert admin_client.post(f"{API}/admin/users/{user_a}/suspend", json={"reason": "   no   "}).status_code == 422
    assert admin_client.post(f"{API}/admin/users/{user_a}/suspend", json={}).status_code == 422
    assert admin_client.post(f"{API}/admin/users/9999/suspend", json={"reason": REASON}).status_code == 404


def test_notify_user(admin_client, user_client, db_session) -> None:
    client_a, user_a = user_client("a")
    response = admin_client.post(
        f"{API}/admin/users/{user_a}/notify",
        json={"title": "Actualiza tu foto", "body": "Tu foto de perfil no cumple las normas.", "link": "/profile"},
    )
    assert response.status_code == 204
    [notification] = [n for n in client_a.get(f"{API}/notifications").json()["items"] if n["type"] == "ADMIN_MESSAGE"]
    assert notification["title"] == "Actualiza tu foto" and notification["link"] == "/profile"
    assert [entry.action for entry in actions(db_session, target_id=user_a)] == ["NOTIFY_USER"]

    bad_link = admin_client.post(
        f"{API}/admin/users/{user_a}/notify", json={"title": "Hola", "body": "x", "link": "https://otro.com"}
    )
    assert bad_link.status_code == 422


def test_admin_users_routes_require_admin(user_client, register_restaurant, make_client) -> None:
    client_a, user_a = user_client("a")
    restaurant_client, _ = register_restaurant("r")
    anonymous = make_client()
    for client, expected in [(client_a, 403), (restaurant_client, 403), (anonymous, 401)]:
        assert client.get(f"{API}/admin/users").status_code == expected
        assert client.get(f"{API}/admin/users/{user_a}").status_code == expected
        assert client.post(f"{API}/admin/users/{user_a}/suspend", json={"reason": REASON}).status_code == expected
        assert client.patch(f"{API}/admin/users/{user_a}/role", json={"role": "admin"}).status_code == expected
