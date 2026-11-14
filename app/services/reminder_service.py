"""Tareas periódicas de los planes (plan de la fase 2, sección 7.7).

Todas son **idempotentes** (estado en la fila + `dedupe_key` único en las notificaciones) y usan
`FOR UPDATE SKIP LOCKED` en PostgreSQL (SQLite lo ignora), así que es seguro ejecutarlas desde
varios workers a la vez. Cada una hace su propio commit y devuelve cuántas filas procesó.
"""

from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.time import ensure_utc, to_local
from app.models.establishment import Establishment
from app.models.notification import Notification, NotificationType
from app.models.plan import Plan
from app.models.user import User
from app.services.notification_service import notify
from app.services.review_service import check_can_review

DAY_NAMES = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MONTH_NAMES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)


def describe_when(scheduled_at: datetime, now: datetime) -> str:
    """"hoy a las 19:30", "mañana a las 08:00" o "el viernes 20 de noviembre a las 19:30" (hora de Colombia)."""
    local, today = to_local(scheduled_at), to_local(now).date()
    hour = local.strftime("%H:%M")
    if local.date() == today:
        return f"hoy a las {hour}"
    if local.date() == today + timedelta(days=1):
        return f"mañana a las {hour}"
    return f"el {DAY_NAMES[local.weekday()]} {local.day} de {MONTH_NAMES[local.month - 1]} a las {hour}"


async def _names(session: AsyncSession, ids: set[int]) -> dict[int, str]:
    if not ids:
        return {}
    rows = await session.execute(select(Establishment.id, Establishment.name).where(Establishment.id.in_(ids)))
    return {row.id: row.name for row in rows.all()}


async def dispatch_due_reminders(session: AsyncSession, now: datetime) -> int:
    """Envía los recordatorios vencidos una sola vez. Devuelve cuántos notificó.

    Si el plan ya empezó (el ciclo estuvo detenido), se marca como enviado sin notificar.
    """
    now = ensure_utc(now)
    plans = list(
        (
            await session.scalars(
                select(Plan)
                .where(Plan.status == "SCHEDULED", Plan.reminder_at <= now, Plan.reminder_sent_at.is_(None))
                .order_by(Plan.reminder_at)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    names = await _names(session, {plan.establishment_id for plan in plans})
    sent = 0
    for plan in plans:
        scheduled_at = ensure_utc(plan.scheduled_at)
        if scheduled_at > now:
            name = names.get(plan.establishment_id, "el establecimiento")
            created = await notify(
                session,
                plan.user_id,
                NotificationType.PLAN_REMINDER,
                f"Tu plan en {name} es {describe_when(scheduled_at, now)}",
                f"{plan.title or 'Tu plan'}: {plan.party_size} "
                f"{'persona' if plan.party_size == 1 else 'personas'}. Revisa los detalles y cómo llegar.",
                link=f"/plans/{plan.id}",
                data={"plan_id": plan.id, "establishment_id": plan.establishment_id},
                dedupe_key=f"plan-reminder:{plan.id}:{ensure_utc(plan.reminder_at).isoformat()}",
            )
            sent += created is not None
        plan.reminder_sent_at = now
    await session.commit()
    return sent


async def complete_past_plans(session: AsyncSession, now: datetime) -> int:
    """Marca COMPLETED los planes que pasaron hace `PLAN_COMPLETE_AFTER_HOURS` e invita a reseñar
    (`REVIEW_PROMPT`) si el usuario aún puede reseñar ese local. Devuelve cuántos completó."""
    now = ensure_utc(now)
    limit = now - timedelta(hours=settings.plan_complete_after_hours)
    plans = list(
        (
            await session.scalars(
                select(Plan)
                .where(Plan.status == "SCHEDULED", Plan.scheduled_at < limit)
                .order_by(Plan.scheduled_at)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    for plan in plans:
        plan.status = "COMPLETED"
        establishment = await session.get(Establishment, plan.establishment_id)
        user = await session.get(User, plan.user_id)
        if establishment is None or user is None or establishment.status != "APPROVED":
            continue
        if await check_can_review(session, user, establishment) is not None:
            continue  # ya lo reseñó, es el dueño, cuenta suspendida…
        await notify(
            session,
            plan.user_id,
            NotificationType.REVIEW_PROMPT,
            f"¿Cómo te fue en {establishment.name}?",
            "Cuéntale a otros con tu reseña: solo te toma un minuto.",
            link=f"/establishments/{establishment.id}?review=1#reviews",
            data={"plan_id": plan.id, "establishment_id": establishment.id},
            dedupe_key=f"plan-review-prompt:{plan.id}",
        )
    await session.commit()
    return len(plans)


async def purge_old_notifications(session: AsyncSession, now: datetime) -> int:
    """Borra las notificaciones LEÍDAS con más de `NOTIFICATIONS_RETENTION_DAYS` días."""
    cutoff = ensure_utc(now) - timedelta(days=settings.notifications_retention_days)
    result = await session.execute(
        delete(Notification).where(Notification.read_at.is_not(None), Notification.created_at < cutoff)
    )
    await session.commit()
    return result.rowcount or 0


async def run_cycle(session: AsyncSession, now: datetime) -> dict[str, int]:
    return {
        "reminders": await dispatch_due_reminders(session, now),
        "completed": await complete_past_plans(session, now),
        "purged": await purge_old_notifications(session, now),
    }
