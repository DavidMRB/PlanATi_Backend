import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from app.core.csrf import CSRF_HEADER_NAME
from app.models.notification import Notification, NotificationType
from app.services.notification_service import notify, notify_admins
from tests.conftest import API


def _notify_many(db_session, user_id: int, count: int, *, start: datetime | None = None) -> list[int]:
    """Crea `count` notificaciones con fechas crecientes; devuelve sus ids en orden de creación."""
    base = start or datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)

    async def scenario() -> list[int]:
        async with db_session() as session:
            created = []
            for index in range(count):
                notification = await notify(
                    session, user_id, NotificationType.ADMIN_MESSAGE, f"Aviso {index + 1}", f"Cuerpo {index + 1}",
                    link=f"/avisos/{index + 1}", data={"n": index + 1},
                )
                notification.created_at = base + timedelta(minutes=index)
                created.append(notification)
            await session.commit()
            return [notification.id for notification in created]

    return asyncio.run(scenario())


def test_requires_session(make_client) -> None:
    client = make_client()
    assert client.get(f"{API}/notifications").status_code == 401
    assert client.get(f"{API}/notifications/unread-count").status_code == 401
    assert client.post(f"{API}/notifications/read-all").status_code == 401


def test_list_is_paginated_newest_first(user_client, db_session) -> None:
    client, user_id = user_client("a")
    _notify_many(db_session, user_id, 3)

    page = client.get(f"{API}/notifications", params={"limit": 2}).json()
    assert (page["total"], page["skip"], page["limit"]) == (3, 0, 2)
    assert [item["title"] for item in page["items"]] == ["Aviso 3", "Aviso 2"]
    first = page["items"][0]
    assert first["type"] == "ADMIN_MESSAGE"
    assert first["link"] == "/avisos/3"
    assert first["data"] == {"n": 3}
    assert first["is_read"] is False and first["read_at"] is None
    assert first["created_at"].endswith(("Z", "+00:00"))

    rest = client.get(f"{API}/notifications", params={"skip": 2, "limit": 2}).json()
    assert [item["title"] for item in rest["items"]] == ["Aviso 1"]

    assert client.get(f"{API}/notifications", params={"limit": 51}).status_code == 422


def test_mark_one_and_all_as_read(user_client, db_session) -> None:
    client, user_id = user_client("a")
    first, second, third = _notify_many(db_session, user_id, 3)
    assert client.get(f"{API}/notifications/unread-count").json() == {"count": 3}

    assert client.post(f"{API}/notifications/{second}/read").status_code == 204
    assert client.post(f"{API}/notifications/{second}/read").status_code == 204  # idempotente
    assert client.get(f"{API}/notifications/unread-count").json() == {"count": 2}

    unread = client.get(f"{API}/notifications", params={"unread_only": True}).json()
    assert unread["total"] == 2
    assert {item["id"] for item in unread["items"]} == {first, third}
    read_item = next(item for item in client.get(f"{API}/notifications").json()["items"] if item["id"] == second)
    assert read_item["is_read"] is True and read_item["read_at"] is not None

    assert client.post(f"{API}/notifications/read-all").status_code == 204
    assert client.get(f"{API}/notifications/unread-count").json() == {"count": 0}
    assert client.get(f"{API}/notifications", params={"unread_only": True}).json()["total"] == 0


def test_notifications_are_isolated_between_users(user_client, db_session) -> None:
    alice, alice_id = user_client("a")
    bob, bob_id = user_client("b")
    (alice_notification,) = _notify_many(db_session, alice_id, 1)
    _notify_many(db_session, bob_id, 2)

    assert alice.get(f"{API}/notifications").json()["total"] == 1
    assert bob.get(f"{API}/notifications/unread-count").json() == {"count": 2}

    # Un recurso ajeno responde 404, no 403.
    assert bob.post(f"{API}/notifications/{alice_notification}/read").status_code == 404
    assert bob.delete(f"{API}/notifications/{alice_notification}").status_code == 404
    assert bob.post(f"{API}/notifications/999999/read").status_code == 404

    # Marcar todas solo afecta las propias.
    assert bob.post(f"{API}/notifications/read-all").status_code == 204
    assert alice.get(f"{API}/notifications/unread-count").json() == {"count": 1}


def test_delete_notification(user_client, db_session) -> None:
    client, user_id = user_client("a")
    notification_id, _ = _notify_many(db_session, user_id, 2)
    assert client.delete(f"{API}/notifications/{notification_id}").status_code == 204
    assert client.delete(f"{API}/notifications/{notification_id}").status_code == 404
    assert client.get(f"{API}/notifications").json()["total"] == 1


def test_write_routes_are_csrf_protected(user_client, db_session) -> None:
    client, user_id = user_client("a")
    (notification_id,) = _notify_many(db_session, user_id, 1)
    client.headers.pop(CSRF_HEADER_NAME)
    assert client.post(f"{API}/notifications/{notification_id}/read").status_code == 403
    assert client.post(f"{API}/notifications/read-all").status_code == 403


def test_dedupe_key_prevents_duplicates(user_client, db_session) -> None:
    _, user_id = user_client("a")

    async def scenario() -> tuple[bool, bool, bool, int]:
        async with db_session() as session:
            first = await notify(session, user_id, NotificationType.PLAN_REMINDER, "Recordatorio", "Hoy", dedupe_key="plan:1")
            # Misma transacción, todavía sin commit: también se detecta.
            same_transaction = await notify(session, user_id, NotificationType.PLAN_REMINDER, "Recordatorio", "Hoy", dedupe_key="plan:1")
            await session.commit()
        async with db_session() as session:
            later = await notify(session, user_id, NotificationType.PLAN_REMINDER, "Recordatorio", "Hoy", dedupe_key="plan:1")
            other_key = await notify(session, user_id, NotificationType.PLAN_REMINDER, "Recordatorio", "Hoy", dedupe_key="plan:2")
            await session.commit()
            total = await session.scalar(select(func.count(Notification.id)).where(Notification.user_id == user_id))
        return first is not None and other_key is not None, same_transaction is None, later is None, int(total)

    created, deduped_in_transaction, deduped_later, total = asyncio.run(scenario())
    assert created and deduped_in_transaction and deduped_later
    assert total == 2


def test_notify_does_not_commit_and_trims_long_titles(user_client, db_session) -> None:
    _, user_id = user_client("a")

    async def scenario() -> tuple[int, str]:
        async with db_session() as session:
            await notify(session, user_id, NotificationType.ADMIN_MESSAGE, "x" * 200, "cuerpo")
            await session.rollback()  # sin commit, la notificación no queda guardada
            notification = await notify(session, user_id, NotificationType.ADMIN_MESSAGE, "y" * 200, "cuerpo")
            await session.commit()
            total = await session.scalar(select(func.count(Notification.id)))
            return int(total), notification.title

    total, title = asyncio.run(scenario())
    assert total == 1
    assert len(title) == 150 and title.endswith("…")


def test_notify_admins_reaches_only_active_admins(make_client, create_user, db_session) -> None:
    active_admin = create_user("admin1@planati.com", role="admin")
    other_admin = create_user("admin2@planati.com", role="admin")
    inactive_admin = create_user("admin3@planati.com", role="admin", status="PENDING_PHONE", phone_verified=False)
    regular_user = create_user("usuario@planati.com")

    async def scenario() -> dict[int, int]:
        async with db_session() as session:
            await notify_admins(session, NotificationType.ADMIN_REPORT_OPENED, "Nuevo reporte", "Revisa la cola", link="/admin/reports")
            await session.commit()
            rows = await session.execute(select(Notification.user_id, func.count()).group_by(Notification.user_id))
            return dict(rows.all())

    counts = asyncio.run(scenario())
    assert counts == {active_admin: 1, other_admin: 1}
    assert inactive_admin not in counts and regular_user not in counts


def test_owner_is_notified_when_establishment_is_approved(register_restaurant, admin_client) -> None:
    owner, data = register_restaurant("a")
    # El restaurante PENDING puede consultar su bandeja.
    assert owner.get(f"{API}/notifications/unread-count").json() == {"count": 0}

    response = admin_client.post(f"{API}/admin/establishments/{data['establishment_id']}/approve")
    assert response.status_code == 200

    page = owner.get(f"{API}/notifications").json()
    assert page["total"] == 1
    notification = page["items"][0]
    assert notification["type"] == "ESTABLISHMENT_APPROVED"
    assert "Parrilla A" in notification["body"]
    assert notification["link"] == "/restaurant/dashboard"
    assert notification["data"] == {"establishment_id": data["establishment_id"]}
    # El admin que aprueba no recibe nada.
    assert admin_client.get(f"{API}/notifications").json()["total"] == 0


def test_owner_is_notified_with_reason_when_establishment_is_rejected(register_restaurant, admin_client) -> None:
    owner, data = register_restaurant("a")
    response = admin_client.post(
        f"{API}/admin/establishments/{data['establishment_id']}/reject",
        json={"reason": "Las fotos no corresponden al local"},
    )
    assert response.status_code == 200

    (notification,) = owner.get(f"{API}/notifications").json()["items"]
    assert notification["type"] == "ESTABLISHMENT_REJECTED"
    assert notification["body"].startswith("Motivo: Las fotos no corresponden al local. Corrige")
    assert notification["link"] == "/restaurant/status"


def test_failed_transition_does_not_notify(approved_restaurant, admin_client) -> None:
    owner, establishment_id = approved_restaurant("a")
    assert admin_client.post(f"{API}/admin/establishments/{establishment_id}/approve").status_code == 409
    assert owner.get(f"{API}/notifications").json()["total"] == 1  # solo la de la primera aprobación
