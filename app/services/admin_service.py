"""Administración de cuentas y establecimientos (plan de la fase 2, sección 7.5).

Igual que `moderation_service`, estas funciones NO hacen commit (salvo que se indique): la ruta
hace un único `commit()` con la acción, la bitácora y las notificaciones.

Protecciones: un admin no puede cambiarse el rol ni suspenderse a sí mismo, y el sistema nunca se
queda sin un admin activo.
"""

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import local_day_start, to_local, utcnow
from app.models.establishment import Establishment, EstablishmentImage, MenuItem
from app.models.notification import NotificationType
from app.models.plan import Plan
from app.models.report import Report
from app.models.review import Review, ReviewReply
from app.models.user import User
from app.services.establishment_service import ensure_in_service_area
from app.services.moderation_service import (
    AlreadyAppliedError,
    ModerationConflictError,
    ModerationError,
    ModerationNotFoundError,
    jsonable,
    record_moderation_action,
)
from app.services.notification_service import notify

# GUIA #7 TEMA: Cadenas, listas, tuplas y diccionarios -> conjunto (set) con los roles que un administrador puede asignar; se valida con `in`.
ASSIGNABLE_ROLES = {"user", "admin"}


# --- Conteos reutilizables ----------------------------------------------------------------------


def user_open_reports_expr() -> Any:
    """Reportes abiertos sobre la cuenta o sobre sus reseñas (correlacionada con `User.id`)."""
    return (
        select(func.count(Report.id))
        .where(
            Report.status == "OPEN",
            or_(
                and_(Report.target_type == "USER", Report.target_id == User.id),
                and_(
                    Report.target_type == "REVIEW",
                    Report.target_id.in_(select(Review.id).where(Review.user_id == User.id)),
                ),
            ),
        )
        .scalar_subquery()
    )


def user_reviews_count_expr() -> Any:
    return select(func.count(Review.id)).where(Review.user_id == User.id).scalar_subquery()


def user_establishment_id_expr() -> Any:
    return select(func.min(Establishment.id)).where(Establishment.owner_id == User.id).scalar_subquery()


def establishment_open_reports_expr() -> Any:
    """Reportes abiertos sobre el local, sus fotos, su menú o sus respuestas (correlacionada)."""
    return (
        select(func.count(Report.id))
        .where(
            Report.status == "OPEN",
            or_(
                and_(Report.target_type == "ESTABLISHMENT", Report.target_id == Establishment.id),
                and_(
                    Report.target_type == "ESTABLISHMENT_IMAGE",
                    Report.target_id.in_(
                        select(EstablishmentImage.id).where(EstablishmentImage.establishment_id == Establishment.id)
                    ),
                ),
                and_(
                    Report.target_type == "MENU_ITEM",
                    Report.target_id.in_(select(MenuItem.id).where(MenuItem.establishment_id == Establishment.id)),
                ),
                and_(
                    Report.target_type == "REVIEW_REPLY",
                    Report.target_id.in_(
                        select(ReviewReply.id).where(ReviewReply.establishment_id == Establishment.id)
                    ),
                ),
            ),
        )
        .scalar_subquery()
    )


# --- Usuarios -----------------------------------------------------------------------------------


async def list_users(
    session: AsyncSession,
    *,
    search: str | None = None,
    role: str | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[tuple[User, int, int, int | None]], int]:
    """[(usuario, reseñas, reportes abiertos, id de su establecimiento)], total."""
    conditions: list[Any] = []
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        conditions.append(
            or_(
                User.full_name.ilike(pattern),
                User.nickname.ilike(pattern),
                User.email.ilike(pattern),
                User.phone_number.ilike(pattern),
            )
        )
    if role:
        conditions.append(User.role == role)
    if status:
        conditions.append(User.status == status)
    else:
        # Las lápidas de cuentas eliminadas (B8) solo aparecen si se filtra por status=DELETED.
        conditions.append(User.status != "DELETED")
    total = await session.scalar(select(func.count(User.id)).where(*conditions))
    rows = await session.execute(
        select(User, user_reviews_count_expr(), user_open_reports_expr(), user_establishment_id_expr())
        .where(*conditions)
        .order_by(User.created_at.desc(), User.id.desc())
        .offset(skip)
        .limit(limit)
    )
    return [(user, int(reviews or 0), int(reports or 0), est) for user, reviews, reports, est in rows.all()], int(
        total or 0
    )


async def get_user(session: AsyncSession, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise ModerationNotFoundError("Usuario no encontrado")
    return user


async def user_counts(session: AsyncSession, user_id: int) -> tuple[int, int, int | None]:
    row = (
        await session.execute(
            select(user_reviews_count_expr(), user_open_reports_expr(), user_establishment_id_expr()).where(
                User.id == user_id
            )
        )
    ).one()
    return int(row[0] or 0), int(row[1] or 0), row[2]


async def count_other_active_admins(session: AsyncSession, user_id: int) -> int:
    count = await session.scalar(
        select(func.count(User.id)).where(User.role == "admin", User.status == "ACTIVE", User.id != user_id)
    )
    return int(count or 0)


async def _ensure_not_last_admin(session: AsyncSession, user: User, message: str) -> None:
    if user.role == "admin" and user.status == "ACTIVE" and await count_other_active_admins(session, user.id) == 0:
        raise ModerationError(message)


def _ensure_not_deleted(user: User) -> None:
    if user.status == "DELETED":
        raise ModerationConflictError("La cuenta fue eliminada por su titular.")


async def change_role(session: AsyncSession, admin: User, user: User, role: str) -> User:
    _ensure_not_deleted(user)
    role = role.strip().lower()
    if role not in ASSIGNABLE_ROLES:
        raise ModerationError("El rol permitido es 'user' o 'admin'.")
    if user.id == admin.id:
        raise ModerationError("No puedes cambiar tu propio rol.")
    if user.role == "restaurant":
        raise ModerationError("El rol de una cuenta de establecimiento no se puede cambiar.")
    if user.role == role:
        return user
    if user.role == "admin":
        await _ensure_not_last_admin(session, user, "No puedes quitar el rol al último administrador activo.")
    previous = user.role
    user.role = role
    await record_moderation_action(
        session, admin.id, "CHANGE_ROLE", "USER", user.id, details={"before": previous, "after": role}
    )
    return user


async def suspend_user(session: AsyncSession, admin: User, user: User, reason: str, *, now: datetime | None = None) -> User:
    _ensure_not_deleted(user)
    if user.id == admin.id:
        raise ModerationError("No puedes suspender tu propia cuenta.")
    if user.status == "SUSPENDED":
        raise AlreadyAppliedError("La cuenta ya está suspendida.")
    await _ensure_not_last_admin(session, user, "No puedes suspender al último administrador activo.")
    previous = user.status
    user.status = "SUSPENDED"
    user.suspension_reason = reason.strip()
    user.suspended_at = now or utcnow()
    await record_moderation_action(
        session, admin.id, "SUSPEND_USER", "USER", user.id, reason=reason, details={"previous_status": previous}
    )
    # La verá al reactivarse su cuenta (mientras está suspendida la API le responde 403).
    await notify(
        session,
        user.id,
        NotificationType.ACCOUNT_SUSPENDED,
        "Tu cuenta fue suspendida",
        f"Un administrador suspendió tu cuenta. Motivo: {user.suspension_reason}",
        data={"user_id": user.id},
    )
    return user


async def reactivate_user(session: AsyncSession, admin: User, user: User, note: str | None = None) -> User:
    if user.status != "SUSPENDED":
        raise AlreadyAppliedError("La cuenta no está suspendida.")
    # Las cuentas de establecimiento no pasan por OTP (su acceso depende de la aprobación del local).
    user.status = "ACTIVE" if user.phone_verified or user.role == "restaurant" else "PENDING_PHONE"
    user.suspension_reason = None
    user.suspended_at = None
    await record_moderation_action(
        session, admin.id, "REACTIVATE_USER", "USER", user.id, reason=note, details={"new_status": user.status}
    )
    await notify(
        session,
        user.id,
        NotificationType.ACCOUNT_REACTIVATED,
        "Tu cuenta fue reactivada",
        "Ya puedes volver a usar PlanATi. Recuerda respetar las normas de la comunidad.",
        link="/legal/community-guidelines",
        data={"user_id": user.id},
    )
    return user


async def send_admin_message(
    session: AsyncSession, admin: User, user: User, *, title: str, body: str, link: str | None
) -> None:
    _ensure_not_deleted(user)
    await notify(session, user.id, NotificationType.ADMIN_MESSAGE, title, body, link=link, data={"from_admin": True})
    await record_moderation_action(
        session, admin.id, "NOTIFY_USER", "USER", user.id, details={"title": title, "body": body, "link": link}
    )


# --- Establecimientos ---------------------------------------------------------------------------


async def suspend_establishment(
    session: AsyncSession, admin: User, establishment: Establishment, reason: str
) -> Establishment:
    if establishment.status == "SUSPENDED":
        raise AlreadyAppliedError("El establecimiento ya está suspendido.")
    if establishment.status != "APPROVED":
        raise ModerationConflictError("Solo se puede suspender un establecimiento aprobado.")
    establishment.status = "SUSPENDED"
    establishment.suspension_reason = reason.strip()
    await record_moderation_action(
        session, admin.id, "SUSPEND_ESTABLISHMENT", "ESTABLISHMENT", establishment.id, reason=reason
    )
    await notify(
        session,
        establishment.owner_id,
        NotificationType.ESTABLISHMENT_SUSPENDED,
        f"{establishment.name} fue suspendido",
        f"Tu establecimiento ya no es visible en PlanATi. Motivo: {establishment.suspension_reason}",
        link="/restaurant/status",
        data={"establishment_id": establishment.id},
    )
    # Los usuarios con planes futuros en el local se enteran (el plan no se cancela solo).
    from app.services.plan_service import future_scheduled_user_ids

    for user_id in await future_scheduled_user_ids(session, establishment.id, utcnow()):
        await notify(
            session,
            user_id,
            NotificationType.PLAN_AFFECTED,
            f"{establishment.name} no está disponible",
            "El establecimiento de uno de tus planes fue suspendido y ya no aparece en PlanATi. "
            "Revisa tus planes: puedes cancelarlo o eliminarlo.",
            link="/plans",
            data={"establishment_id": establishment.id},
        )
    return establishment


async def reactivate_establishment(
    session: AsyncSession, admin: User, establishment: Establishment, note: str | None = None
) -> Establishment:
    if establishment.status != "SUSPENDED":
        raise AlreadyAppliedError("El establecimiento no está suspendido.")
    establishment.status = "APPROVED"
    establishment.suspension_reason = None
    await record_moderation_action(
        session, admin.id, "REACTIVATE_ESTABLISHMENT", "ESTABLISHMENT", establishment.id, reason=note
    )
    await notify(
        session,
        establishment.owner_id,
        NotificationType.ESTABLISHMENT_REACTIVATED,
        f"{establishment.name} fue reactivado",
        "Tu establecimiento vuelve a ser visible en PlanATi.",
        link="/restaurant/dashboard",
        data={"establishment_id": establishment.id},
    )
    return establishment


async def update_establishment_as_admin(
    session: AsyncSession,
    admin: User,
    establishment: Establishment,
    changes: dict[str, Any],
    reason: str | None,
) -> Establishment:
    """Edita el perfil como si fuera el establecimiento; bitácora con antes/después y aviso al dueño."""
    ensure_in_service_area(changes.get("latitude"), changes.get("longitude"))
    diff = {
        field: {"before": getattr(establishment, field), "after": value}
        for field, value in changes.items()
        if getattr(establishment, field) != value
    }
    for field, value in changes.items():
        setattr(establishment, field, value)
    if not diff:
        return establishment
    await record_moderation_action(
        session, admin.id, "EDIT_ESTABLISHMENT", "ESTABLISHMENT", establishment.id, reason=reason, details=diff
    )
    await notify(
        session,
        establishment.owner_id,
        NotificationType.ESTABLISHMENT_EDITED_BY_ADMIN,
        "Un administrador editó tu establecimiento",
        f"Se actualizaron datos del perfil de {establishment.name}."
        + (f" Motivo: {reason}" if reason else "")
        + " Revisa tu perfil.",
        link="/restaurant/profile",
        data={"establishment_id": establishment.id, "fields": sorted(diff)},
    )
    return establishment


async def record_catalog_edit(
    session: AsyncSession,
    admin: User,
    establishment: Establishment,
    operation: str,
    details: dict[str, Any] | None = None,
    *,
    now: datetime | None = None,
) -> None:
    """Bitácora `EDIT_CATALOG` de una edición del catálogo, fotos u horarios hecha por un admin.

    Se llama ANTES de la operación del catálogo, que hace el único commit; si la operación falla
    (404, 400, 409) no se confirma nada. Al dueño se le avisa una sola vez por día.
    """
    await record_moderation_action(
        session,
        admin.id,
        "EDIT_CATALOG",
        "ESTABLISHMENT",
        establishment.id,
        details={"operation": operation, **jsonable(details or {})},
    )
    day = to_local(now or utcnow()).date().isoformat()
    await notify(
        session,
        establishment.owner_id,
        NotificationType.ESTABLISHMENT_EDITED_BY_ADMIN,
        "Un administrador editó tu catálogo",
        f"Un administrador actualizó el menú, las fotos o los horarios de {establishment.name}. Revisa tu panel.",
        link="/restaurant/dashboard",
        data={"establishment_id": establishment.id},
        dedupe_key=f"admin-catalog-edit:{establishment.id}:{day}",
    )


# --- Dashboard ----------------------------------------------------------------------------------


async def dashboard_counts(session: AsyncSession, *, now: datetime | None = None) -> dict[str, int]:
    now = now or utcnow()

    async def count(model_column: Any, *conditions: Any) -> int:
        return int(await session.scalar(select(func.count(model_column)).where(*conditions)) or 0)

    return {
        "users_count": await count(User.id, User.status != "DELETED"),
        "establishments_count": await count(Establishment.id),
        "reviews_count": await count(Review.id),
        "pending_establishments": await count(Establishment.id, Establishment.status == "PENDING"),
        "suspended_establishments": await count(Establishment.id, Establishment.status == "SUSPENDED"),
        "suspended_users": await count(User.id, User.status == "SUSPENDED"),
        "reviews_last_7_days": await count(Review.id, Review.created_at >= local_day_start(now - timedelta(days=6))),
        "scheduled_plans": await count(Plan.id, Plan.status == "SCHEDULED", Plan.scheduled_at >= now),
        "establishments_without_location": await count(
            Establishment.id,
            Establishment.status.in_(("PENDING", "APPROVED")),
            or_(Establishment.latitude.is_(None), Establishment.longitude.is_(None)),
        ),
    }
