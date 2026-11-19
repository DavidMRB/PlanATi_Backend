"""Reportes de contenido (plan de la fase 2, secciones 7.3 y 7.5).

- Cualquier cuenta activa reporta contenido visible que no sea suyo, una vez por destino y hasta
  `REPORTS_PER_DAY_LIMIT` al día. El primer reporte abierto de un destino avisa a los admins.
- Resolver o descartar un reporte cierra **todos** los reportes abiertos del mismo destino y avisa a
  quienes reportaron. La acción sobre el contenido se delega en `moderation_service`/`admin_service`.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.time import ensure_utc, local_day_start, utcnow
from app.models.establishment import Establishment, EstablishmentImage, MenuItem
from app.models.notification import NotificationType
from app.models.report import Report
from app.models.review import Review, ReviewImage, ReviewReply
from app.models.user import User
from app.services import admin_service, moderation_service
from app.services.moderation_service import (
    AUTO_HIDE_REASON,
    AlreadyAppliedError,
    ModerationConflictError,
    ModerationError,
    ModerationNotFoundError,
    ModerationRateLimitError,
    category_label,
    record_moderation_action,
)
from app.services.notification_service import notify, notify_admins
from app.services.review_service import display_name

ResolveAction = Literal["NONE", "BLOCK_COMMENT", "HIDE_CONTENT", "DELETE_CONTENT", "SUSPEND_OWNER"]

TARGET_LABELS = {
    "REVIEW": "una reseña",
    "REVIEW_REPLY": "la respuesta de un establecimiento",
    "REVIEW_IMAGE": "una foto de una reseña",
    "ESTABLISHMENT": "un establecimiento",
    "ESTABLISHMENT_IMAGE": "una foto de un establecimiento",
    "MENU_ITEM": "un producto del menú",
    "USER": "un usuario",
}
REASON_LABELS = {
    "SPAM": "Spam o publicidad",
    "OFFENSIVE": "Contenido ofensivo",
    "FALSE_INFO": "Información falsa",
    "INAPPROPRIATE_IMAGE": "Imagen inapropiada",
    "OTHER": "Otro motivo",
}


@dataclass
class Target:
    """Destino de un reporte ya cargado."""

    type: str
    id: int
    obj: Any
    # Cuenta responsable del contenido (autor de la reseña, dueño del local, el propio usuario…).
    owner_id: int | None
    # ¿Lo ve el público? Solo se puede reportar lo que se ve.
    visible: bool
    establishment_id: int | None = None
    preview: dict[str, Any] = field(default_factory=dict)


async def _establishment(session: AsyncSession, establishment_id: int) -> Establishment | None:
    return await session.get(Establishment, establishment_id)


async def load_target(session: AsyncSession, target_type: str, target_id: int) -> Target | None:
    """Carga el destino y arma su vista previa para el admin (con el texto original). None si no existe."""
    if target_type == "REVIEW":
        review = await session.get(Review, target_id)
        if review is None:
            return None
        establishment = await _establishment(session, review.establishment_id)
        return Target(
            target_type,
            target_id,
            review,
            review.user_id,
            review.status == "VISIBLE" and establishment is not None and establishment.status == "APPROVED",
            review.establishment_id,
            {
                "text": review.comment,
                "image_url": review.images[0].image_url if review.images else None,
                "name": establishment.name if establishment else None,
                "rating": review.rating,
                "status": review.status,
                "comment_status": review.comment_status,
                "owner_name": display_name(review.author),
            },
        )
    if target_type == "REVIEW_REPLY":
        reply = await session.get(ReviewReply, target_id)
        if reply is None:
            return None
        review = await session.get(Review, reply.review_id)
        establishment = await _establishment(session, reply.establishment_id)
        return Target(
            target_type,
            target_id,
            reply,
            establishment.owner_id if establishment else None,
            review is not None
            and review.status == "VISIBLE"
            and establishment is not None
            and establishment.status == "APPROVED",
            reply.establishment_id,
            {
                "text": reply.comment,
                "name": establishment.name if establishment else None,
                "review_id": reply.review_id,
                "comment_status": reply.comment_status,
            },
        )
    if target_type == "REVIEW_IMAGE":
        image = await session.get(ReviewImage, target_id)
        if image is None:
            return None
        review = await session.get(Review, image.review_id)
        establishment = await _establishment(session, review.establishment_id) if review else None
        return Target(
            target_type,
            target_id,
            image,
            review.user_id if review else None,
            review is not None
            and review.status == "VISIBLE"
            and establishment is not None
            and establishment.status == "APPROVED",
            review.establishment_id if review else None,
            {
                "image_url": image.image_url,
                "name": establishment.name if establishment else None,
                "review_id": image.review_id,
            },
        )
    if target_type == "ESTABLISHMENT":
        establishment = await _establishment(session, target_id)
        if establishment is None:
            return None
        return Target(
            target_type,
            target_id,
            establishment,
            establishment.owner_id,
            establishment.status == "APPROVED",
            establishment.id,
            {
                "name": establishment.name,
                "text": establishment.description,
                "image_url": establishment.profile_image_url,
                "status": establishment.status,
            },
        )
    if target_type == "ESTABLISHMENT_IMAGE":
        image = await session.get(EstablishmentImage, target_id)
        if image is None:
            return None
        establishment = await _establishment(session, image.establishment_id)
        return Target(
            target_type,
            target_id,
            image,
            establishment.owner_id if establishment else None,
            establishment is not None and establishment.status == "APPROVED",
            image.establishment_id,
            {"image_url": image.image_url, "name": establishment.name if establishment else None, "text": image.caption},
        )
    if target_type == "MENU_ITEM":
        item = await session.get(MenuItem, target_id)
        if item is None:
            return None
        establishment = await _establishment(session, item.establishment_id)
        return Target(
            target_type,
            target_id,
            item,
            establishment.owner_id if establishment else None,
            establishment is not None and establishment.status == "APPROVED",
            item.establishment_id,
            {
                "name": item.name,
                "text": item.description,
                "image_url": item.image_url,
                "establishment_name": establishment.name if establishment else None,
                "is_available": item.is_available,
            },
        )
    if target_type == "USER":
        user = await session.get(User, target_id)
        if user is None:
            return None
        return Target(
            target_type,
            target_id,
            user,
            user.id,
            user.status != "SUSPENDED",
            None,
            {"name": display_name(user), "image_url": user.picture, "status": user.status},
        )
    return None


# --- Crear --------------------------------------------------------------------------------------


async def count_open_reports(session: AsyncSession, target_type: str, target_id: int) -> int:
    count = await session.scalar(
        select(func.count(Report.id)).where(
            Report.status == "OPEN", Report.target_type == target_type, Report.target_id == target_id
        )
    )
    return int(count or 0)


async def create_report(
    session: AsyncSession,
    reporter: User,
    target_type: str,
    target_id: int,
    reason: str,
    details: str | None,
    *,
    now: datetime | None = None,
) -> Report:
    now = ensure_utc(now or utcnow())
    reporter_id = reporter.id
    target = await load_target(session, target_type, target_id)
    if target is None or not target.visible:
        raise ModerationNotFoundError("Contenido no encontrado")
    if target.owner_id == reporter_id:
        raise ModerationError("No puedes reportar tu propio contenido.")
    existing = await session.scalar(
        select(Report.id).where(
            Report.reporter_id == reporter_id, Report.target_type == target_type, Report.target_id == target_id
        )
    )
    if existing is not None:
        raise ModerationConflictError("Ya reportaste este contenido.", report_id=existing)
    created_today = await session.scalar(
        select(func.count(Report.id)).where(Report.reporter_id == reporter_id, Report.created_at >= local_day_start(now))
    )
    if int(created_today or 0) >= settings.reports_per_day_limit:
        raise ModerationRateLimitError("Alcanzaste el límite diario de reportes. Inténtalo de nuevo mañana.")

    first_open = await count_open_reports(session, target_type, target_id) == 0
    report = Report(
        reporter_id=reporter_id, target_type=target_type, target_id=target_id, reason=reason, details=details
    )
    session.add(report)
    try:
        await session.flush()
    except IntegrityError as error:
        await session.rollback()
        raise ModerationConflictError("Ya reportaste este contenido.") from error

    if first_open:
        await notify_admins(
            session,
            NotificationType.ADMIN_REPORT_OPENED,
            "Nuevo reporte de contenido",
            f"Se reportó {TARGET_LABELS[target_type]} por: {REASON_LABELS.get(reason, reason)}.",
            link="/admin/reports",
            data={"report_id": report.id, "target_type": target_type, "target_id": target_id},
        )
    threshold = settings.report_auto_hide_threshold
    if (
        threshold > 0
        and target_type == "REVIEW"
        and target.obj.status == "VISIBLE"
        and await count_open_reports(session, target_type, target_id) >= threshold
    ):
        await moderation_service.hide_review(session, None, target.obj, category=None, reason=AUTO_HIDE_REASON)

    report_id = report.id
    await session.commit()
    created = await session.get(Report, report_id)
    assert created is not None
    return created


# --- Cola del admin -----------------------------------------------------------------------------


async def get_report(session: AsyncSession, report_id: int) -> Report:
    report = await session.get(Report, report_id)
    if report is None:
        raise ModerationNotFoundError("Reporte no encontrado")
    return report


async def list_reports(
    session: AsyncSession,
    *,
    status: Literal["OPEN", "RESOLVED", "DISMISSED", "ALL"] = "OPEN",
    target_type: str | None = None,
    reason: str | None = None,
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[tuple[Report, User | None, int, Target | None]], int]:
    """[(reporte, quien reportó, reportes abiertos sobre el mismo destino, destino)], total."""
    conditions: list[Any] = []
    if status != "ALL":
        conditions.append(Report.status == status)
    if target_type:
        conditions.append(Report.target_type == target_type)
    if reason:
        conditions.append(Report.reason == reason)
    total = await session.scalar(select(func.count(Report.id)).where(*conditions))
    rows = (
        await session.execute(
            select(Report, User)
            .outerjoin(User, User.id == Report.reporter_id)
            .where(*conditions)
            .order_by(Report.created_at.desc(), Report.id.desc())
            .offset(skip)
            .limit(limit)
        )
    ).all()
    # Un destino por clave distinta de la página (como mucho `limit` consultas pequeñas).
    keys = {(report.target_type, report.target_id) for report, _ in rows}
    counts: dict[tuple[str, int], int] = {}
    targets: dict[tuple[str, int], Target | None] = {}
    for key in keys:
        counts[key] = await count_open_reports(session, *key)
        targets[key] = await load_target(session, *key)
    return [
        (report, reporter, counts[(report.target_type, report.target_id)], targets[(report.target_type, report.target_id)])
        for report, reporter in rows
    ], int(total or 0)


# --- Resolver y descartar -----------------------------------------------------------------------

_NOT_APPLICABLE = "Esta acción no aplica a este tipo de contenido."


async def _apply_action(
    session: AsyncSession, admin: User, target: Target, action: ResolveAction, category: str, note: str | None
) -> None:
    reason = note or category_label(category)
    kind, obj = target.type, target.obj

    async def suspend_account(user_id: int | None) -> None:
        if user_id is None:
            raise ModerationNotFoundError("No se encontró la cuenta responsable.")
        user = await admin_service.get_user(session, user_id)
        await admin_service.suspend_user(session, admin, user, reason)

    async def suspend_place(establishment_id: int | None) -> None:
        establishment = await _establishment(session, establishment_id) if establishment_id else None
        if establishment is None:
            raise ModerationNotFoundError("Establecimiento no encontrado")
        await admin_service.suspend_establishment(session, admin, establishment, reason)

    if kind == "REVIEW":
        if action == "BLOCK_COMMENT":
            await moderation_service.block_review_comment(session, admin, obj, category=category, note=note)
        elif action == "HIDE_CONTENT":
            await moderation_service.hide_review(session, admin, obj, category=category, reason=note)
        elif action == "DELETE_CONTENT":
            await moderation_service.delete_review_as_admin(session, admin, obj, reason=reason)
        else:
            await suspend_account(target.owner_id)
    elif kind == "REVIEW_REPLY":
        if action in ("BLOCK_COMMENT", "HIDE_CONTENT"):
            await moderation_service.block_reply(session, admin, obj, category=category, note=note)
        elif action == "DELETE_CONTENT":
            await moderation_service.delete_reply_as_admin(session, admin, obj, reason=reason)
        else:
            await suspend_place(target.establishment_id)
    elif kind == "REVIEW_IMAGE":
        if action == "BLOCK_COMMENT":
            raise ModerationError(_NOT_APPLICABLE)
        if action in ("HIDE_CONTENT", "DELETE_CONTENT"):
            await moderation_service.delete_review_image(session, admin, obj, reason=reason)
        else:
            await suspend_account(target.owner_id)
    elif kind == "ESTABLISHMENT":
        if action in ("BLOCK_COMMENT", "DELETE_CONTENT"):
            raise ModerationError(_NOT_APPLICABLE)
        if action == "HIDE_CONTENT":
            await suspend_place(target.establishment_id)
        else:
            await suspend_account(target.owner_id)
    elif kind == "ESTABLISHMENT_IMAGE":
        if action == "BLOCK_COMMENT":
            raise ModerationError(_NOT_APPLICABLE)
        if action in ("HIDE_CONTENT", "DELETE_CONTENT"):
            await moderation_service.delete_establishment_image_as_admin(session, admin, obj, reason=reason)
        else:
            await suspend_place(target.establishment_id)
    elif kind == "MENU_ITEM":
        if action == "BLOCK_COMMENT":
            raise ModerationError(_NOT_APPLICABLE)
        if action == "HIDE_CONTENT":
            await moderation_service.hide_menu_item(session, admin, obj, reason=reason)
        elif action == "DELETE_CONTENT":
            await moderation_service.delete_menu_item_as_admin(session, admin, obj, reason=reason)
        else:
            await suspend_place(target.establishment_id)
    elif kind == "USER":
        if action in ("BLOCK_COMMENT", "DELETE_CONTENT"):
            raise ModerationError(_NOT_APPLICABLE)
        await suspend_account(target.owner_id)


async def _close_reports(
    session: AsyncSession,
    admin: User,
    report: Report,
    *,
    status: Literal["RESOLVED", "DISMISSED"],
    note: str | None,
    now: datetime,
) -> list[Report]:
    reports = list(
        (
            await session.scalars(
                select(Report).where(
                    Report.status == "OPEN",
                    Report.target_type == report.target_type,
                    Report.target_id == report.target_id,
                )
            )
        ).all()
    )
    for item in reports:
        item.status = status
        item.resolved_by_id = admin.id
        item.resolution_note = note
        item.resolved_at = now
    return reports


async def _notify_reporters(session: AsyncSession, reports: list[Report], *, action_taken: bool) -> None:
    # Quien eliminó su cuenta (lápida, B8) ya no recibe avisos.
    reporter_ids = {item.reporter_id for item in reports}
    deleted = (
        set(
            (
                await session.scalars(
                    select(User.id).where(User.id.in_(reporter_ids), User.status == "DELETED")
                )
            ).all()
        )
        if reporter_ids
        else set()
    )
    for item in reports:
        if item.reporter_id in deleted:
            continue
        await notify(
            session,
            item.reporter_id,
            NotificationType.REPORT_RESOLVED,
            "Revisamos tu reporte",
            (
                f"Gracias por reportar {TARGET_LABELS.get(item.target_type, 'contenido')}. "
                + (
                    "Tomamos medidas según las normas de la comunidad."
                    if action_taken
                    else "No encontramos una infracción a las normas de la comunidad."
                )
            ),
            data={"report_id": item.id, "target_type": item.target_type, "target_id": item.target_id},
        )


async def resolve_report(
    session: AsyncSession,
    admin: User,
    report_id: int,
    action: ResolveAction,
    category: str | None,
    note: str | None,
    *,
    now: datetime | None = None,
) -> Report:
    report = await get_report(session, report_id)
    if report.status != "OPEN":
        raise ModerationConflictError("El reporte ya fue cerrado.")
    if action != "NONE":
        if category is None:
            raise ModerationError("Indica la categoría de la infracción.")
        target = await load_target(session, report.target_type, report.target_id)
        if target is None:
            raise ModerationNotFoundError(
                "El contenido reportado ya no existe. Resuelve el reporte sin acción o descártalo."
            )
        try:
            await _apply_action(session, admin, target, action, category, note)
        except AlreadyAppliedError:
            pass  # el contenido ya está en el estado pedido: basta con cerrar los reportes
    closed = await _close_reports(session, admin, report, status="RESOLVED", note=note, now=ensure_utc(now or utcnow()))
    await record_moderation_action(
        session,
        admin.id,
        "RESOLVE_REPORT",
        report.target_type,
        report.target_id,
        reason=note,
        details={"action": action, "category": category, "report_ids": [item.id for item in closed]},
    )
    await _notify_reporters(session, closed, action_taken=action != "NONE")
    report_id = report.id
    await session.commit()
    return await get_report(session, report_id)


async def dismiss_report(
    session: AsyncSession, admin: User, report_id: int, note: str | None, *, now: datetime | None = None
) -> Report:
    report = await get_report(session, report_id)
    if report.status != "OPEN":
        raise ModerationConflictError("El reporte ya fue cerrado.")
    closed = await _close_reports(session, admin, report, status="DISMISSED", note=note, now=ensure_utc(now or utcnow()))
    await record_moderation_action(
        session,
        admin.id,
        "DISMISS_REPORT",
        report.target_type,
        report.target_id,
        reason=note,
        details={"report_ids": [item.id for item in closed]},
    )
    await _notify_reporters(session, closed, action_taken=False)
    report_id = report.id
    await session.commit()
    return await get_report(session, report_id)


async def reports_about(
    session: AsyncSession, conditions: list[Any], *, limit: int = 10
) -> list[Report]:
    rows = await session.scalars(
        select(Report).where(*conditions).order_by(Report.created_at.desc(), Report.id.desc()).limit(limit)
    )
    return list(rows.all())
