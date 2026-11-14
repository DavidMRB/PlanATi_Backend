"""B6: crear, listar, editar, cancelar y eliminar planes; validaciones de horario, ítems y recordatorio."""

import asyncio
from datetime import timedelta

from app.core.config import settings
from app.core.time import UTC, utcnow
from app.models.plan import Plan
from tests.conftest import API
from tests.moderation_helpers import REASON, notification_types
from tests.plan_helpers import add_product, create_plan, in_days, iso, next_local, put_schedules


def test_create_plan_computes_total_on_server(approved_restaurant, user_client) -> None:
    owner, establishment_id = approved_restaurant("a")
    picada = add_product(owner, "Picada", "25000")
    jugo = add_product(owner, "Jugo", "6000")
    client, _ = user_client("u")

    plan = create_plan(
        client,
        establishment_id,
        party_size=4,
        notes="  Mesa en terraza  ",
        reminder_minutes_before=120,
        total_amount="1",  # cualquier total del cliente se ignora
        items=[
            {"menu_item_id": picada, "quantity": 2, "notes": "sin cebolla"},
            {"menu_item_id": jugo, "quantity": 1},
            {"menu_item_id": picada, "quantity": 1},  # repetido: se fusiona
        ],
    )
    assert plan["total_amount"] == "81000.00"
    assert plan["currency"] == "COP" and plan["status"] == "SCHEDULED"
    assert plan["title"] == "Plan en Parrilla A"
    assert plan["notes"] == "Mesa en terraza"
    assert plan["items_count"] == 2
    by_name = {item["name"]: item for item in plan["items"]}
    assert by_name["Picada"]["quantity"] == 3 and by_name["Picada"]["notes"] == "sin cebolla"
    assert by_name["Picada"]["subtotal"] == "75000.00" and by_name["Picada"]["price_changed"] is False
    assert plan["establishment"]["name"] == "Parrilla A"
    assert plan["establishment"]["latitude"] is not None
    assert plan["establishment_available"] is True and plan["outside_schedule"] is False


def test_scheduled_at_is_stored_in_utc_and_validated_in_local_time(approved_restaurant, user_client) -> None:
    owner, establishment_id = approved_restaurant("a")
    put_schedules(owner, [(0, "18:00", "23:00")])  # solo lunes en la noche
    client, _ = user_client("u")
    monday_evening = next_local(0, 19, 30)
    plan = create_plan(client, establishment_id, monday_evening, reminder_minutes_before=60)
    # 19:30 en Colombia (-05:00) = 00:30 UTC del martes; se valida contra el lunes local.
    expected = monday_evening.astimezone(UTC)
    assert expected.hour == 0 and expected.minute == 30 and expected.weekday() == 1
    assert plan["scheduled_at"] == expected.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert plan["reminder_at"] == (expected - timedelta(minutes=60)).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Los segundos se descartan.
    seconds = create_plan(client, establishment_id, monday_evening.replace(second=45) + timedelta(days=7))
    assert ":30:00" in seconds["scheduled_at"]


def test_closed_hours_and_midnight_segments(approved_restaurant, user_client) -> None:
    owner, establishment_id = approved_restaurant("a")
    put_schedules(owner, [(0, "08:00", "15:00"), (5, "18:00", "02:00")])
    client, _ = user_client("u")

    closed = create_plan(client, establishment_id, next_local(0, 16, 0), expected=400)
    assert closed == {"detail": "El establecimiento está cerrado en ese horario.", "code": "CLOSED"}
    create_plan(client, establishment_id, next_local(0, 8, 0))  # la apertura se incluye
    create_plan(client, establishment_id, next_local(0, 15, 0), expected=400)  # el cierre se excluye
    # Sábado 18:00–02:00 cubre la madrugada del domingo.
    create_plan(client, establishment_id, next_local(6, 1, 30))
    create_plan(client, establishment_id, next_local(6, 2, 0), expected=400)


def test_establishment_without_schedules_accepts_any_time(approved_restaurant, user_client) -> None:
    _, establishment_id = approved_restaurant("a")
    client, _ = user_client("u")
    create_plan(client, establishment_id, next_local(2, 3, 0))


def test_validation_errors(approved_restaurant, user_client) -> None:
    owner, establishment_id = approved_restaurant("a")
    client, _ = user_client("u")
    naive = in_days(3).replace(tzinfo=None).isoformat()
    response = client.post(f"{API}/plans", json={"establishment_id": establishment_id, "scheduled_at": naive})
    assert response.status_code == 422
    create_plan(client, establishment_id, utcnow() + timedelta(minutes=5), expected=400)
    create_plan(client, establishment_id, utcnow() + timedelta(days=settings.plan_max_days_ahead + 2), expected=400)
    create_plan(client, establishment_id, party_size=0, expected=422)
    create_plan(client, establishment_id, party_size=51, expected=422)
    create_plan(client, establishment_id, reminder_minutes_before=45, expected=422)
    create_plan(client, establishment_id, items=[{"menu_item_id": 1, "quantity": 100}], expected=422)
    create_plan(client, establishment_id, items=[{"menu_item_id": i} for i in range(1, 32)], expected=422)
    create_plan(client, 9999, expected=404)

    soon = utcnow() + timedelta(minutes=40)
    past_reminder = create_plan(client, establishment_id, soon, reminder_minutes_before=60, expected=400)
    assert past_reminder["code"] == "REMINDER_IN_PAST"
    create_plan(client, establishment_id, soon, reminder_minutes_before=15)


def test_items_must_belong_to_establishment_and_be_available(approved_restaurant, user_client) -> None:
    owner, establishment_id = approved_restaurant("a")
    other_owner, _ = approved_restaurant("b")
    hidden = add_product(owner, "Agotado", "1000", is_available=False)
    foreign = add_product(other_owner, "Ajeno", "1000")
    client, _ = user_client("u")
    body = create_plan(
        client, establishment_id, items=[{"menu_item_id": hidden}, {"menu_item_id": foreign}], expected=400
    )
    assert body["code"] == "INVALID_ITEMS" and body["invalid_item_ids"] == [hidden, foreign]


def test_only_approved_establishments(register_restaurant, user_client) -> None:
    _, pending = register_restaurant("p")
    client, _ = user_client("u")
    create_plan(client, pending["establishment_id"], expected=404)


def test_permissions(approved_restaurant, user_client, admin_client, make_client, create_user) -> None:
    owner, establishment_id = approved_restaurant("a")
    for client in (owner, admin_client):
        assert create_plan(client, establishment_id, expected=403)["code"] == "ROLE_NOT_ALLOWED"
        assert client.get(f"{API}/plans").status_code == 403
    assert make_client().get(f"{API}/plans").status_code == 401
    create_user("pendiente@planati.com", phone_verified=False, status="PENDING_PHONE")
    pending = make_client()
    pending.post(f"{API}/auth/login", json={"email": "pendiente@planati.com", "password": "Password123!"})
    assert create_plan(pending, establishment_id, expected=403)["code"] == "PHONE_NOT_VERIFIED"


def test_max_active_plans(approved_restaurant, user_client, monkeypatch) -> None:
    _, establishment_id = approved_restaurant("a")
    client, _ = user_client("u")
    monkeypatch.setattr(settings, "plan_max_active", 1)
    plan = create_plan(client, establishment_id)
    create_plan(client, establishment_id, in_days(4), expected=429)
    client.post(f"{API}/plans/{plan['id']}/cancel")
    create_plan(client, establishment_id, in_days(4))


def test_list_upcoming_and_range(approved_restaurant, user_client) -> None:
    _, establishment_id = approved_restaurant("a")
    client, _ = user_client("u")
    other, _ = user_client("v")
    late = create_plan(client, establishment_id, in_days(20))
    soon = create_plan(client, establishment_id, in_days(2))
    create_plan(other, establishment_id, in_days(3))

    upcoming = client.get(f"{API}/plans").json()
    assert upcoming["total"] == 2
    assert [item["id"] for item in upcoming["items"]] == [soon["id"], late["id"]]
    assert "items" not in upcoming["items"][0]

    ranged = client.get(f"{API}/plans", params={"from": iso(in_days(1)), "to": iso(in_days(10))}).json()
    assert [item["id"] for item in ranged["items"]] == [soon["id"]]
    assert client.get(f"{API}/plans", params={"from": iso(in_days(1)), "to": iso(in_days(100))}).status_code == 400
    assert client.get(f"{API}/plans", params={"from": iso(in_days(1))}).status_code == 400
    assert client.get(f"{API}/plans", params={"from": iso(in_days(5)), "to": iso(in_days(1))}).status_code == 400
    naive = in_days(1).replace(tzinfo=None).isoformat()
    assert client.get(f"{API}/plans", params={"from": naive, "to": iso(in_days(5))}).status_code == 422

    client.post(f"{API}/plans/{soon['id']}/cancel")
    scheduled = client.get(f"{API}/plans", params={"status": "SCHEDULED"}).json()
    assert [item["id"] for item in scheduled["items"]] == [late["id"]]


def test_other_users_plans_are_not_found(approved_restaurant, user_client) -> None:
    _, establishment_id = approved_restaurant("a")
    client, _ = user_client("u")
    other, _ = user_client("v")
    plan_id = create_plan(client, establishment_id)["id"]
    assert other.get(f"{API}/plans/{plan_id}").status_code == 404
    assert other.patch(f"{API}/plans/{plan_id}", json={"party_size": 3}).status_code == 404
    assert other.post(f"{API}/plans/{plan_id}/cancel").status_code == 404
    assert other.delete(f"{API}/plans/{plan_id}").status_code == 404
    assert other.get(f"{API}/plans/{plan_id}/calendar.ics").status_code == 404
    assert client.get(f"{API}/plans/{plan_id}").status_code == 200


def test_patch_recalculates_total_and_resets_reminder(approved_restaurant, user_client, db_session) -> None:
    owner, establishment_id = approved_restaurant("a")
    picada = add_product(owner, "Picada", "25000")
    jugo = add_product(owner, "Jugo", "6000")
    client, _ = user_client("u")
    plan = create_plan(
        client, establishment_id, reminder_minutes_before=60, items=[{"menu_item_id": picada, "quantity": 2}]
    )

    # El local sube el precio: el plan conserva el congelado y lo avisa.
    owner.patch(f"{API}/restaurant/products/{picada}", json={"price": "30000"})
    detail = client.get(f"{API}/plans/{plan['id']}").json()
    assert detail["total_amount"] == "50000.00"
    assert detail["items"][0]["current_price"] == "30000.00" and detail["items"][0]["price_changed"] is True
    assert detail["prices_changed"] is True

    # Reemplazar los ítems recalcula con los precios actuales.
    updated = client.patch(
        f"{API}/plans/{plan['id']}", json={"items": [{"menu_item_id": picada}, {"menu_item_id": jugo, "quantity": 2}]}
    ).json()
    assert updated["total_amount"] == "42000.00" and updated["prices_changed"] is False

    # Simula un recordatorio ya enviado y luego cambia la fecha: se reprograma.
    async def mark_sent() -> None:
        async with db_session() as session:
            row = await session.get(Plan, plan["id"])
            row.reminder_sent_at = utcnow()
            await session.commit()

    asyncio.run(mark_sent())
    assert client.get(f"{API}/plans/{plan['id']}").json()["reminder_sent_at"] is not None
    moved = client.patch(f"{API}/plans/{plan['id']}", json={"scheduled_at": iso(in_days(5, 18))}).json()
    assert moved["reminder_sent_at"] is None
    assert moved["reminder_at"] != plan["reminder_at"]
    no_reminder = client.patch(f"{API}/plans/{plan['id']}", json={"reminder_minutes_before": None}).json()
    assert no_reminder["reminder_at"] is None

    renamed = client.patch(f"{API}/plans/{plan['id']}", json={"title": "Cumpleaños de Ana", "party_size": 6}).json()
    assert renamed["title"] == "Cumpleaños de Ana" and renamed["party_size"] == 6
    assert client.patch(f"{API}/plans/{plan['id']}", json={"title": ""}).json()["title"] == "Plan en Parrilla A"
    assert client.patch(f"{API}/plans/{plan['id']}", json={"party_size": None}).status_code == 422
    assert client.patch(f"{API}/plans/{plan['id']}", json={"items": None}).status_code == 422
    assert client.patch(f"{API}/plans/{plan['id']}", json={"establishment_id": 5}).json()["establishment"]["id"] == establishment_id


def test_patch_validates_new_time(approved_restaurant, user_client) -> None:
    owner, establishment_id = approved_restaurant("a")
    put_schedules(owner, [(0, "08:00", "15:00")])
    client, _ = user_client("u")
    plan = create_plan(client, establishment_id, next_local(0, 9, 0))
    response = client.patch(f"{API}/plans/{plan['id']}", json={"scheduled_at": iso(next_local(0, 20, 0))})
    assert response.status_code == 400 and response.json()["code"] == "CLOSED"


def test_cancel_and_delete(approved_restaurant, user_client) -> None:
    _, establishment_id = approved_restaurant("a")
    client, _ = user_client("u")
    plan = create_plan(client, establishment_id)
    cancelled = client.post(f"{API}/plans/{plan['id']}/cancel")
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "CANCELLED"
    assert client.post(f"{API}/plans/{plan['id']}/cancel").status_code == 409
    assert client.patch(f"{API}/plans/{plan['id']}", json={"party_size": 2}).status_code == 409
    assert client.delete(f"{API}/plans/{plan['id']}").status_code == 204
    assert client.get(f"{API}/plans/{plan['id']}").status_code == 404


def test_detail_flags_after_changes(approved_restaurant, user_client, admin_client) -> None:
    owner, establishment_id = approved_restaurant("a")
    put_schedules(owner, [(0, "08:00", "22:00")])
    product = add_product(owner, "Picada", "25000")
    client, _ = user_client("u")
    plan = create_plan(client, establishment_id, next_local(0, 20, 0), items=[{"menu_item_id": product}])

    put_schedules(owner, [(0, "08:00", "15:00")])
    owner.delete(f"{API}/restaurant/products/{product}")
    detail = client.get(f"{API}/plans/{plan['id']}").json()
    assert detail["outside_schedule"] is True
    assert detail["items"][0]["current_price"] is None and detail["items"][0]["price_changed"] is True
    assert detail["items"][0]["name"] == "Picada" and detail["total_amount"] == "25000.00"

    assert admin_client.get(f"{API}/admin/dashboard").json()["scheduled_plans"] == 1
    admin_client.post(f"{API}/admin/establishments/{establishment_id}/suspend", json={"reason": REASON})
    detail = client.get(f"{API}/plans/{plan['id']}").json()
    assert detail["establishment_available"] is False
    assert "PLAN_AFFECTED" in notification_types(client)
    edit = client.patch(f"{API}/plans/{plan['id']}", json={"party_size": 2})
    assert edit.status_code == 400 and edit.json()["code"] == "ESTABLISHMENT_UNAVAILABLE"
    assert client.post(f"{API}/plans/{plan['id']}/cancel").status_code == 200
