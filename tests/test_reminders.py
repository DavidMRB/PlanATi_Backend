"""B6: recordatorios (una sola vez), cierre de planes con invitación a reseñar y purga de notificaciones.

Se llaman los servicios directamente con un `now` fijo (las pruebas no arrancan el ciclo del lifespan).
"""

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, select

from app.core.time import LOCAL_TZ, UTC
from app.models.notification import Notification
from app.models.plan import Plan
from app.services import reminder_service
from tests.conftest import API
from tests.moderation_helpers import post_review

NOW = datetime(2026, 11, 20, 15, 0, tzinfo=UTC)  # viernes 10:00 en Colombia


def _insert_plan(db_session, user_id: int, establishment_id: int, scheduled_at: datetime, **fields) -> int:
    async def scenario() -> int:
        async with db_session() as session:
            minutes = fields.pop("reminder_minutes_before", None)
            plan = Plan(
                user_id=user_id,
                establishment_id=establishment_id,
                title="Plan de prueba",
                scheduled_at=scheduled_at,
                party_size=2,
                reminder_minutes_before=minutes,
                reminder_at=scheduled_at - timedelta(minutes=minutes) if minutes else None,
                total_amount=Decimal("0"),
                **fields,
            )
            session.add(plan)
            await session.commit()
            return plan.id

    return asyncio.run(scenario())


def _run(db_session, func_, now: datetime) -> int:
    async def scenario() -> int:
        async with db_session() as session:
            return await func_(session, now)

    return asyncio.run(scenario())


def _notifications(db_session, user_id: int, type_: str) -> list[Notification]:
    async def scenario() -> list[Notification]:
        async with db_session() as session:
            rows = await session.scalars(
                select(Notification).where(Notification.user_id == user_id, Notification.type == type_)
            )
            return list(rows.all())

    return asyncio.run(scenario())


def _plan(db_session, plan_id: int) -> Plan:
    async def scenario() -> Plan:
        async with db_session() as session:
            return await session.get(Plan, plan_id)

    return asyncio.run(scenario())


def test_reminder_is_sent_once(approved_restaurant, user_client, db_session) -> None:
    _, establishment_id = approved_restaurant("a")
    _, user_id = user_client("u")
    scheduled = NOW + timedelta(hours=4, minutes=30)  # hoy 14:30 en Colombia
    plan_id = _insert_plan(db_session, user_id, establishment_id, scheduled, reminder_minutes_before=300)

    assert _run(db_session, reminder_service.dispatch_due_reminders, NOW - timedelta(hours=1)) == 0
    assert _run(db_session, reminder_service.dispatch_due_reminders, NOW) == 1
    assert _run(db_session, reminder_service.dispatch_due_reminders, NOW + timedelta(minutes=1)) == 0
    [notice] = _notifications(db_session, user_id, "PLAN_REMINDER")
    assert notice.title == "Tu plan en Parrilla A es hoy a las 14:30"
    assert notice.link == f"/plans/{plan_id}"
    assert _plan(db_session, plan_id).reminder_sent_at is not None


def test_late_reminder_is_marked_without_notifying(approved_restaurant, user_client, db_session) -> None:
    _, establishment_id = approved_restaurant("a")
    _, user_id = user_client("u")
    plan_id = _insert_plan(db_session, user_id, establishment_id, NOW - timedelta(minutes=10), reminder_minutes_before=60)
    assert _run(db_session, reminder_service.dispatch_due_reminders, NOW) == 0
    assert _notifications(db_session, user_id, "PLAN_REMINDER") == []
    assert _plan(db_session, plan_id).reminder_sent_at is not None


def test_cancelled_plans_get_no_reminder(approved_restaurant, user_client, db_session) -> None:
    _, establishment_id = approved_restaurant("a")
    _, user_id = user_client("u")
    _insert_plan(db_session, user_id, establishment_id, NOW + timedelta(hours=1), reminder_minutes_before=120,
                 status="CANCELLED")
    assert _run(db_session, reminder_service.dispatch_due_reminders, NOW) == 0


def test_rescheduled_plan_reminds_again(approved_restaurant, user_client, db_session) -> None:
    """Tras editar la fecha, `reminder_sent_at` vuelve a None y el nuevo recordatorio tiene otra clave."""
    _, establishment_id = approved_restaurant("a")
    _, user_id = user_client("u")
    plan_id = _insert_plan(db_session, user_id, establishment_id, NOW + timedelta(minutes=30), reminder_minutes_before=60)
    _run(db_session, reminder_service.dispatch_due_reminders, NOW)

    async def reschedule() -> None:
        async with db_session() as session:
            plan = await session.get(Plan, plan_id)
            plan.scheduled_at = NOW + timedelta(days=1, hours=1)
            plan.reminder_at = plan.scheduled_at - timedelta(minutes=60)
            plan.reminder_sent_at = None
            await session.commit()

    asyncio.run(reschedule())
    assert _run(db_session, reminder_service.dispatch_due_reminders, NOW + timedelta(days=1)) == 1
    titles = [n.title for n in _notifications(db_session, user_id, "PLAN_REMINDER")]
    assert sorted(titles) == ["Tu plan en Parrilla A es hoy a las 10:30", "Tu plan en Parrilla A es hoy a las 11:00"]


def test_describe_when() -> None:
    now = datetime(2026, 11, 20, 15, 0, tzinfo=UTC)  # viernes 20 de noviembre, 10:00 local
    local = lambda *args: datetime(*args, tzinfo=LOCAL_TZ)  # noqa: E731
    assert reminder_service.describe_when(local(2026, 11, 20, 19, 30), now) == "hoy a las 19:30"
    assert reminder_service.describe_when(local(2026, 11, 21, 8, 0), now) == "mañana a las 08:00"
    assert reminder_service.describe_when(local(2026, 11, 23, 12, 15), now) == "el lunes 23 de noviembre a las 12:15"


def test_complete_past_plans_invites_to_review(approved_restaurant, user_client, db_session) -> None:
    _, establishment_id = approved_restaurant("a")
    client_u, user_u = user_client("u")
    client_v, user_v = user_client("v")
    post_review(client_v, establishment_id, rating=5)  # v ya reseñó: no se le invita
    old = NOW - timedelta(hours=4)
    plan_u = _insert_plan(db_session, user_u, establishment_id, old)
    plan_v = _insert_plan(db_session, user_v, establishment_id, old)
    recent = _insert_plan(db_session, user_u, establishment_id, NOW - timedelta(hours=1))

    assert _run(db_session, reminder_service.complete_past_plans, NOW) == 2
    assert _run(db_session, reminder_service.complete_past_plans, NOW) == 0
    assert _plan(db_session, plan_u).status == "COMPLETED"
    assert _plan(db_session, plan_v).status == "COMPLETED"
    assert _plan(db_session, recent).status == "SCHEDULED"

    [prompt] = _notifications(db_session, user_u, "REVIEW_PROMPT")
    assert prompt.title == "¿Cómo te fue en Parrilla A?"
    assert prompt.link == f"/establishments/{establishment_id}?review=1#reviews"
    assert _notifications(db_session, user_v, "REVIEW_PROMPT") == []
    # El plan completado ya no se puede editar.
    assert client_u.patch(f"{API}/plans/{plan_u}", json={"party_size": 3}).status_code == 409


def test_purge_old_read_notifications(user_client, db_session) -> None:
    _, user_id = user_client("u")

    async def seed() -> None:
        async with db_session() as session:
            old = NOW - timedelta(days=100)
            session.add_all(
                [
                    Notification(user_id=user_id, type="ADMIN_MESSAGE", title="Vieja leída", body="x",
                                 created_at=old, read_at=old),
                    Notification(user_id=user_id, type="ADMIN_MESSAGE", title="Vieja sin leer", body="x", created_at=old),
                    Notification(user_id=user_id, type="ADMIN_MESSAGE", title="Reciente leída", body="x",
                                 created_at=NOW - timedelta(days=5), read_at=NOW),
                ]
            )
            await session.commit()

    asyncio.run(seed())
    assert _run(db_session, reminder_service.purge_old_notifications, NOW) == 1

    async def remaining() -> int:
        async with db_session() as session:
            return await session.scalar(select(func.count(Notification.id)))

    assert asyncio.run(remaining()) == 2


def test_run_cycle(approved_restaurant, user_client, db_session) -> None:
    _, establishment_id = approved_restaurant("a")
    _, user_id = user_client("u")
    _insert_plan(db_session, user_id, establishment_id, NOW + timedelta(minutes=10), reminder_minutes_before=15)
    _insert_plan(db_session, user_id, establishment_id, NOW - timedelta(hours=5))
    result = _run(db_session, reminder_service.run_cycle, NOW)
    assert result == {"reminders": 1, "completed": 1, "purged": 0}


def test_lifespan_starts_and_stops_reminder_worker(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    import app.main as main
    from app.core.config import settings

    events: list[str] = []

    async def fake_loop(stop) -> None:
        events.append("start")
        await stop.wait()
        events.append("stop")

    monkeypatch.setattr(main, "reminders_loop", fake_loop)
    monkeypatch.setattr(settings, "reminders_enabled", True)
    with TestClient(main.app):
        pass
    assert events == ["start", "stop"]

    events.clear()
    monkeypatch.setattr(settings, "reminders_enabled", False)
    with TestClient(main.app):
        pass
    assert events == []
