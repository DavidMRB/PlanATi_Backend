"""Notificaciones dentro de la app.

`notify` y `notify_admins` **no hacen commit**: agregan la notificación a la sesión para que quede
en la misma transacción que la operación que la origina (aprobar un local, publicar una reseña…),
que hace un único `commit()` al final.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utcnow
from app.models.notification import Notification, NotificationType
from app.models.user import User

TITLE_MAX_LENGTH = 150


class NotificationNotFoundError(Exception):
    """La notificación no existe o es de otro usuario (404)."""


def _fit_title(title: str) -> str:
    title = title.strip()
    return title if len(title) <= TITLE_MAX_LENGTH else title[: TITLE_MAX_LENGTH - 1].rstrip() + "…"


async def notify(
    session: AsyncSession,
    user_id: int,
    type_: NotificationType | str,
    title: str,
    body: str,
    *,
    link: str | None = None,
    data: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
) -> Notification | None:
    """Agrega la notificación a la sesión SIN hacer commit. Con un `dedupe_key` ya usado devuelve None."""
    if dedupe_key is not None:
        # La consulta hace autoflush, así que también ve las notificaciones pendientes de esta transacción.
        existing = await session.scalar(select(Notification.id).where(Notification.dedupe_key == dedupe_key))
        if existing is not None:
            return None
    notification = Notification(
        user_id=user_id,
        type=str(type_),
        title=_fit_title(title),
        body=body.strip(),
        link=link,
        data=data,
        dedupe_key=dedupe_key,
    )
    session.add(notification)
    return notification


async def notify_admins(
    session: AsyncSession,
    type_: NotificationType | str,
    title: str,
    body: str,
    *,
    link: str | None = None,
    data: dict[str, Any] | None = None,
) -> None:
    """Notifica a todos los administradores activos (sin commit)."""
    admin_ids = await session.scalars(select(User.id).where(User.role == "admin", User.status == "ACTIVE"))
    for admin_id in admin_ids.all():
        await notify(session, admin_id, type_, title, body, link=link, data=data)


async def list_notifications(
    session: AsyncSession, user_id: int, *, unread_only: bool, skip: int, limit: int
) -> tuple[list[Notification], int]:
    conditions = [Notification.user_id == user_id]
    if unread_only:
        conditions.append(Notification.read_at.is_(None))
    total = await session.scalar(select(func.count(Notification.id)).where(*conditions))
    rows = await session.scalars(
        select(Notification)
        .where(*conditions)
        # El id desempata notificaciones creadas en el mismo segundo.
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(rows.all()), int(total or 0)


async def count_unread(session: AsyncSession, user_id: int) -> int:
    count = await session.scalar(
        select(func.count(Notification.id)).where(Notification.user_id == user_id, Notification.read_at.is_(None))
    )
    return int(count or 0)


async def _get_own(session: AsyncSession, user_id: int, notification_id: int) -> Notification:
    notification = await session.scalar(
        select(Notification).where(Notification.id == notification_id, Notification.user_id == user_id)
    )
    if notification is None:
        raise NotificationNotFoundError("Notificación no encontrada.")
    return notification


async def mark_read(session: AsyncSession, user_id: int, notification_id: int, now: datetime | None = None) -> None:
    notification = await _get_own(session, user_id, notification_id)
    if notification.read_at is None:
        notification.read_at = now or utcnow()
        await session.commit()


async def mark_all_read(session: AsyncSession, user_id: int, now: datetime | None = None) -> int:
    result = await session.execute(
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=now or utcnow())
    )
    await session.commit()
    return result.rowcount or 0


async def delete_notification(session: AsyncSession, user_id: int, notification_id: int) -> None:
    await _get_own(session, user_id, notification_id)
    await session.execute(
        delete(Notification).where(Notification.id == notification_id, Notification.user_id == user_id)
    )
    await session.commit()
