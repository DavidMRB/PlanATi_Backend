"""Moderación de contenido y bitácora (plan de la fase 2, sección 7.5).

Reglas:
- Ninguna función de este módulo hace commit: la ruta (o `report_service`) hace un único `commit()`
  al final, así la acción, la bitácora, el recálculo del promedio y las notificaciones quedan juntos.
- **Bloquear el comentario** (`comment_status=BLOCKED`) conserva la reseña y sus estrellas: no recalcula
  agregados. **Ocultar** (`status=HIDDEN`) retira la reseña entera y sí recalcula.
- Cada acción registra `record_moderation_action(...)` y notifica al afectado.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any, Literal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import ensure_utc
from app.models.establishment import ComboItem, Establishment, EstablishmentImage, MenuItem
from app.models.moderation import ModerationAction
from app.models.notification import NotificationType
from app.models.report import Report
from app.models.review import MODERATION_CATEGORIES, Review, ReviewImage, ReviewReply
from app.models.user import User
from app.services.notification_service import notify
from app.services.rating_service import recalculate_establishment_rating

if TYPE_CHECKING:
    from app.schemas.admin import AdminReviewItem, ModerationActionItem

COMMUNITY_GUIDELINES_LINK = "/legal/community-guidelines"
AUTO_HIDE_REASON = "Oculta automáticamente por reportes; pendiente de revisión."


# --- Errores de dominio (app/main.py los convierte en {"detail", ...extra}) ---------------------


class ModerationError(Exception):
    status_code = 400

    def __init__(self, detail: str, **extra: Any) -> None:
        self.detail = detail
        self.extra = extra
        super().__init__(detail)


class ModerationNotFoundError(ModerationError):
    status_code = 404


class ModerationForbiddenError(ModerationError):
    status_code = 403


class ModerationConflictError(ModerationError):
    status_code = 409


class AlreadyAppliedError(ModerationConflictError):
    """El destino ya está en el estado pedido (p. ej. comentario ya bloqueado).

    Una ruta directa responde 409; al resolver un reporte se ignora (el resultado es el deseado).
    """


class ModerationRateLimitError(ModerationError):
    status_code = 429


# --- Bitácora ----------------------------------------------------------------------------------


def jsonable(value: Any) -> Any:
    """Convierte valores de modelos (Decimal, datetime, time…) en algo que acepta la columna JSON."""
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return ensure_utc(value).isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


async def record_moderation_action(
    session: AsyncSession,
    admin_id: int | None,
    action: str,
    target_type: str,
    target_id: int,
    *,
    reason: str | None = None,
    details: dict[str, Any] | None = None,
) -> ModerationAction:
    """Agrega una entrada a la bitácora SIN hacer commit. `admin_id=None` = acción automática."""
    entry = ModerationAction(
        admin_id=admin_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        reason=reason.strip() if reason else None,
        details=jsonable(details) if details is not None else None,
    )
    session.add(entry)
    return entry


async def list_moderation_actions(
    session: AsyncSession,
    *,
    admin_id: int | None = None,
    action: str | None = None,
    target_type: str | None = None,
    target_id: int | None = None,
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[tuple[ModerationAction, User | None]], int]:
    conditions = []
    if admin_id is not None:
        conditions.append(ModerationAction.admin_id == admin_id)
    if action is not None:
        conditions.append(ModerationAction.action == action)
    if target_type is not None:
        conditions.append(ModerationAction.target_type == target_type)
    if target_id is not None:
        conditions.append(ModerationAction.target_id == target_id)
    total = await session.scalar(select(func.count(ModerationAction.id)).where(*conditions))
    rows = await session.execute(
        select(ModerationAction, User)
        .outerjoin(User, User.id == ModerationAction.admin_id)
        .where(*conditions)
        .order_by(ModerationAction.created_at.desc(), ModerationAction.id.desc())
        .offset(skip)
        .limit(limit)
    )
    return [(entry, admin) for entry, admin in rows.all()], int(total or 0)


def category_label(category: str | None) -> str:
    return MODERATION_CATEGORIES.get(category or "", "Otro motivo")


def _admin_id(admin: User | None) -> int | None:
    return admin.id if admin is not None else None


# --- Reseñas -----------------------------------------------------------------------------------


async def get_review(session: AsyncSession, review_id: int) -> Review:
    review = await session.scalar(
        select(Review).where(Review.id == review_id).execution_options(populate_existing=True)
    )
    if review is None:
        raise ModerationNotFoundError("Reseña no encontrada")
    return review


async def _establishment_name(session: AsyncSession, establishment_id: int) -> str:
    name = await session.scalar(select(Establishment.name).where(Establishment.id == establishment_id))
    return name or "el establecimiento"


def _review_snapshot(review: Review) -> dict[str, Any]:
    return {
        "user_id": review.user_id,
        "establishment_id": review.establishment_id,
        "rating": review.rating,
        "comment": review.comment,
        "images": [image.image_url for image in review.images],
        "status": review.status,
        "comment_status": review.comment_status,
    }


async def block_review_comment(
    session: AsyncSession,
    admin: User,
    review: Review,
    *,
    category: str,
    note: str | None = None,
    remove_images: bool = False,
) -> Review:
    """Sustituye el texto en público por el aviso fijo. Las estrellas siguen contando (sin recálculo)."""
    already_blocked = review.comment_status == "BLOCKED" and not review.flagged_for_review
    if already_blocked and not (remove_images and review.images):
        raise AlreadyAppliedError("El comentario ya está bloqueado.")
    if review.comment is None:
        raise ModerationError("La reseña no tiene comentario. Borra sus imágenes u oculta la reseña.")
    removed_images = [image.image_url for image in review.images] if remove_images else []
    review.comment_status = "BLOCKED"
    review.flagged_for_review = False
    review.moderation_category = category
    review.moderation_reason = note
    if remove_images:
        review.images.clear()
    await record_moderation_action(
        session,
        admin.id,
        "BLOCK_COMMENT",
        "REVIEW",
        review.id,
        reason=note,
        details={"category": category, "comment": review.comment, "removed_images": removed_images},
    )
    name = await _establishment_name(session, review.establishment_id)
    await notify(
        session,
        review.user_id,
        NotificationType.CONTENT_MODERATED,
        f"Tu comentario en {name} fue bloqueado",
        f"Tu comentario en {name} fue bloqueado: {category_label(category)}."
        + (f" Nota del equipo: {note}" if note else "")
        + " Tus estrellas siguen contando. Revisa las normas de la comunidad.",
        link=COMMUNITY_GUIDELINES_LINK,
        data={"review_id": review.id, "establishment_id": review.establishment_id, "category": category},
    )
    return review


async def unblock_review_comment(
    session: AsyncSession, admin: User, review: Review, *, note: str | None = None
) -> Review:
    """Publica de nuevo el comentario; también sirve para aprobar un comentario reescrito tras un bloqueo."""
    if review.comment_status != "BLOCKED":
        raise AlreadyAppliedError("El comentario no está bloqueado.")
    review.comment_status = "VISIBLE"
    review.flagged_for_review = False
    if review.status != "HIDDEN":
        review.moderation_category = None
        review.moderation_reason = None
    await record_moderation_action(
        session, admin.id, "UNBLOCK_COMMENT", "REVIEW", review.id, reason=note, details={"comment": review.comment}
    )
    name = await _establishment_name(session, review.establishment_id)
    await notify(
        session,
        review.user_id,
        NotificationType.CONTENT_RESTORED,
        f"Tu comentario en {name} ya es visible",
        f"Revisamos tu comentario en {name} y ya está publicado." + (f" Nota del equipo: {note}" if note else ""),
        link=f"/establishments/{review.establishment_id}#review-{review.id}",
        data={"review_id": review.id, "establishment_id": review.establishment_id},
    )
    return review


async def hide_review(
    session: AsyncSession,
    admin: User | None,
    review: Review,
    *,
    category: str | None,
    reason: str | None = None,
) -> Review:
    """Retira la reseña entera del público y del promedio (spam, reseña falsa). `admin=None` = automático."""
    if review.status == "HIDDEN":
        raise AlreadyAppliedError("La reseña ya está oculta.")
    review.status = "HIDDEN"
    review.moderation_category = category
    review.moderation_reason = reason
    await session.flush()
    await recalculate_establishment_rating(session, review.establishment_id)
    await record_moderation_action(
        session,
        _admin_id(admin),
        "HIDE_REVIEW",
        "REVIEW",
        review.id,
        reason=reason,
        details={"category": category, "rating": review.rating, "comment": review.comment},
    )
    name = await _establishment_name(session, review.establishment_id)
    motive = f": {category_label(category)}" if category else ""
    await notify(
        session,
        review.user_id,
        NotificationType.CONTENT_MODERATED,
        f"Tu reseña en {name} fue ocultada",
        f"Tu reseña en {name} fue ocultada por moderación{motive}."
        + (f" {reason}" if reason else "")
        + " Puedes verla en Mis reseñas.",
        link=COMMUNITY_GUIDELINES_LINK,
        data={"review_id": review.id, "establishment_id": review.establishment_id, "category": category},
    )
    return review


async def restore_review(session: AsyncSession, admin: User, review: Review, *, note: str | None = None) -> Review:
    if review.status != "HIDDEN":
        raise AlreadyAppliedError("La reseña no está oculta.")
    review.status = "VISIBLE"
    if review.comment_status != "BLOCKED":
        review.moderation_category = None
        review.moderation_reason = None
    await session.flush()
    await recalculate_establishment_rating(session, review.establishment_id)
    await record_moderation_action(session, admin.id, "RESTORE_REVIEW", "REVIEW", review.id, reason=note)
    name = await _establishment_name(session, review.establishment_id)
    await notify(
        session,
        review.user_id,
        NotificationType.CONTENT_RESTORED,
        f"Tu reseña en {name} es visible de nuevo",
        f"Revisamos tu reseña en {name} y la volvimos a publicar.",
        link=f"/establishments/{review.establishment_id}#review-{review.id}",
        data={"review_id": review.id, "establishment_id": review.establishment_id},
    )
    return review


async def delete_review_as_admin(session: AsyncSession, admin: User, review: Review, *, reason: str) -> None:
    """Borrado físico (contenido ilegal). La bitácora guarda una copia del contenido borrado."""
    establishment_id, author_id, review_id = review.establishment_id, review.user_id, review.id
    snapshot = _review_snapshot(review)
    snapshot["reply"] = review.reply.comment if review.reply is not None else None
    await session.delete(review)
    await session.flush()
    await recalculate_establishment_rating(session, establishment_id)
    await record_moderation_action(
        session, admin.id, "DELETE_REVIEW", "REVIEW", review_id, reason=reason, details=snapshot
    )
    name = await _establishment_name(session, establishment_id)
    await notify(
        session,
        author_id,
        NotificationType.CONTENT_MODERATED,
        f"Tu reseña en {name} fue eliminada",
        f"Tu reseña en {name} fue eliminada por incumplir las normas de la comunidad. Motivo: {reason}",
        link=COMMUNITY_GUIDELINES_LINK,
        data={"establishment_id": establishment_id},
    )


# --- Respuestas del establecimiento -------------------------------------------------------------


async def get_reply(session: AsyncSession, reply_id: int) -> ReviewReply:
    reply = await session.scalar(
        select(ReviewReply).where(ReviewReply.id == reply_id).execution_options(populate_existing=True)
    )
    if reply is None:
        raise ModerationNotFoundError("Respuesta no encontrada")
    return reply


async def _owner_of(session: AsyncSession, establishment_id: int) -> tuple[int | None, str]:
    row = (
        await session.execute(
            select(Establishment.owner_id, Establishment.name).where(Establishment.id == establishment_id)
        )
    ).first()
    return (row.owner_id, row.name) if row is not None else (None, "el establecimiento")


async def block_reply(
    session: AsyncSession, admin: User, reply: ReviewReply, *, category: str, note: str | None = None
) -> ReviewReply:
    if reply.comment_status == "BLOCKED" and not reply.flagged_for_review:
        raise AlreadyAppliedError("La respuesta ya está bloqueada.")
    reply.comment_status = "BLOCKED"
    reply.flagged_for_review = False
    reply.moderation_category = category
    reply.moderation_reason = note
    await record_moderation_action(
        session,
        admin.id,
        "BLOCK_REPLY",
        "REVIEW_REPLY",
        reply.id,
        reason=note,
        details={"category": category, "comment": reply.comment, "review_id": reply.review_id},
    )
    owner_id, name = await _owner_of(session, reply.establishment_id)
    if owner_id is not None:
        await notify(
            session,
            owner_id,
            NotificationType.CONTENT_MODERATED,
            "Una respuesta de tu establecimiento fue bloqueada",
            f"La respuesta de {name} a una reseña fue bloqueada: {category_label(category)}."
            + (f" Nota del equipo: {note}" if note else ""),
            link="/restaurant/reviews",
            data={"review_id": reply.review_id, "reply_id": reply.id, "category": category},
        )
    return reply


async def unblock_reply(
    session: AsyncSession, admin: User, reply: ReviewReply, *, note: str | None = None
) -> ReviewReply:
    if reply.comment_status != "BLOCKED":
        raise AlreadyAppliedError("La respuesta no está bloqueada.")
    reply.comment_status = "VISIBLE"
    reply.flagged_for_review = False
    reply.moderation_category = None
    reply.moderation_reason = None
    await record_moderation_action(
        session, admin.id, "UNBLOCK_REPLY", "REVIEW_REPLY", reply.id, reason=note, details={"comment": reply.comment}
    )
    owner_id, name = await _owner_of(session, reply.establishment_id)
    if owner_id is not None:
        await notify(
            session,
            owner_id,
            NotificationType.CONTENT_RESTORED,
            "Tu respuesta ya es visible",
            f"Revisamos la respuesta de {name} y ya está publicada.",
            link="/restaurant/reviews",
            data={"review_id": reply.review_id, "reply_id": reply.id},
        )
    return reply


async def delete_reply_as_admin(session: AsyncSession, admin: User, reply: ReviewReply, *, reason: str) -> None:
    reply_id, review_id, establishment_id, comment = reply.id, reply.review_id, reply.establishment_id, reply.comment
    await session.delete(reply)
    await session.flush()
    await record_moderation_action(
        session,
        admin.id,
        "DELETE_REPLY",
        "REVIEW_REPLY",
        reply_id,
        reason=reason,
        details={"review_id": review_id, "comment": comment},
    )
    owner_id, name = await _owner_of(session, establishment_id)
    if owner_id is not None:
        await notify(
            session,
            owner_id,
            NotificationType.CONTENT_MODERATED,
            "Una respuesta de tu establecimiento fue eliminada",
            f"La respuesta de {name} a una reseña fue eliminada por moderación. Motivo: {reason}",
            link="/restaurant/reviews",
            data={"review_id": review_id},
        )


# --- Imágenes ----------------------------------------------------------------------------------


async def get_review_image(session: AsyncSession, image_id: int) -> ReviewImage:
    image = await session.get(ReviewImage, image_id)
    if image is None:
        raise ModerationNotFoundError("Imagen no encontrada")
    return image


async def delete_review_image(session: AsyncSession, admin: User, image: ReviewImage, *, reason: str) -> None:
    review = await get_review(session, image.review_id)
    image_id, image_url = image.id, image.image_url
    review.images.remove(image)
    await session.flush()
    await record_moderation_action(
        session,
        admin.id,
        "DELETE_REVIEW_IMAGE",
        "REVIEW_IMAGE",
        image_id,
        reason=reason,
        details={"review_id": review.id, "image_url": image_url},
    )
    name = await _establishment_name(session, review.establishment_id)
    await notify(
        session,
        review.user_id,
        NotificationType.CONTENT_MODERATED,
        f"Una foto de tu reseña en {name} fue eliminada",
        f"Eliminamos una foto de tu reseña en {name} por incumplir las normas de la comunidad. Motivo: {reason}",
        link=COMMUNITY_GUIDELINES_LINK,
        data={"review_id": review.id, "establishment_id": review.establishment_id},
    )


async def delete_establishment_image_as_admin(
    session: AsyncSession, admin: User, image: EstablishmentImage, *, reason: str
) -> None:
    image_id, image_url, establishment_id = image.id, image.image_url, image.establishment_id
    await session.delete(image)
    await session.flush()
    await record_moderation_action(
        session,
        admin.id,
        "DELETE_ESTABLISHMENT_IMAGE",
        "ESTABLISHMENT_IMAGE",
        image_id,
        reason=reason,
        details={"establishment_id": establishment_id, "image_url": image_url},
    )
    owner_id, name = await _owner_of(session, establishment_id)
    if owner_id is not None:
        await notify(
            session,
            owner_id,
            NotificationType.CONTENT_MODERATED,
            "Una foto de tu establecimiento fue eliminada",
            f"Eliminamos una foto de {name} por incumplir las normas de la comunidad. Motivo: {reason}",
            link="/restaurant/gallery",
            data={"establishment_id": establishment_id},
        )


# --- Productos y combos ------------------------------------------------------------------------


async def hide_menu_item(session: AsyncSession, admin: User, item: MenuItem, *, reason: str) -> None:
    if not item.is_available:
        raise AlreadyAppliedError("El producto ya no está disponible.")
    item.is_available = False
    await record_moderation_action(
        session, admin.id, "HIDE_MENU_ITEM", "MENU_ITEM", item.id, reason=reason, details={"name": item.name}
    )
    owner_id, name = await _owner_of(session, item.establishment_id)
    if owner_id is not None:
        await notify(
            session,
            owner_id,
            NotificationType.CONTENT_MODERATED,
            f"«{item.name}» fue retirado del menú",
            f"Marcamos «{item.name}» de {name} como no disponible por moderación. Motivo: {reason}",
            link="/restaurant/products",
            data={"establishment_id": item.establishment_id, "menu_item_id": item.id},
        )


async def delete_menu_item_as_admin(session: AsyncSession, admin: User, item: MenuItem, *, reason: str) -> None:
    if not item.is_combo:
        in_combos = await session.scalar(select(func.count(ComboItem.id)).where(ComboItem.product_id == item.id))
        if in_combos:
            raise ModerationConflictError(
                "El producto forma parte de combos. Márcalo como no disponible o retíralo de esos combos."
            )
    item_id, item_name, establishment_id = item.id, item.name, item.establishment_id
    details = {"name": item_name, "price": item.price, "description": item.description, "is_combo": item.is_combo}
    await session.delete(item)
    await session.flush()
    await record_moderation_action(
        session, admin.id, "DELETE_MENU_ITEM", "MENU_ITEM", item_id, reason=reason, details=details
    )
    owner_id, name = await _owner_of(session, establishment_id)
    if owner_id is not None:
        await notify(
            session,
            owner_id,
            NotificationType.CONTENT_MODERATED,
            f"«{item_name}» fue eliminado del menú",
            f"Eliminamos «{item_name}» del menú de {name} por moderación. Motivo: {reason}",
            link="/restaurant/products",
            data={"establishment_id": establishment_id},
        )


# --- Cola de moderación de reseñas ----------------------------------------------------------------


def open_reports_count_expr(target_type: str, target_id_column: Any) -> Any:
    """Subconsulta correlacionada: reportes abiertos sobre un destino."""
    return (
        select(func.count(Report.id))
        .where(Report.status == "OPEN", Report.target_type == target_type, Report.target_id == target_id_column)
        .scalar_subquery()
    )


AdminReviewSort = Literal["recent", "most_reported"]


async def list_reviews_for_admin(
    session: AsyncSession,
    *,
    status: Literal["VISIBLE", "HIDDEN", "ALL"] = "ALL",
    comment_status: Literal["VISIBLE", "BLOCKED"] | None = None,
    flagged_for_review: bool | None = None,
    establishment_id: int | None = None,
    user_id: int | None = None,
    rating: int | None = None,
    has_reports: bool | None = None,
    search: str | None = None,
    sort: AdminReviewSort = "recent",
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[tuple[Review, int]], int]:
    """(reseña, reportes abiertos) con el texto original. `flagged_for_review` incluye las reseñas cuya
    respuesta del establecimiento se reescribió tras un bloqueo."""
    reports = open_reports_count_expr("REVIEW", Review.id)
    conditions: list[Any] = []
    if status != "ALL":
        conditions.append(Review.status == status)
    if comment_status is not None:
        conditions.append(Review.comment_status == comment_status)
    if flagged_for_review is not None:
        reply_flagged = (
            select(ReviewReply.id)
            .where(ReviewReply.review_id == Review.id, ReviewReply.flagged_for_review.is_(True))
            .exists()
        )
        flagged = or_(Review.flagged_for_review.is_(True), reply_flagged)
        conditions.append(flagged if flagged_for_review else ~flagged)
    if establishment_id is not None:
        conditions.append(Review.establishment_id == establishment_id)
    if user_id is not None:
        conditions.append(Review.user_id == user_id)
    if rating is not None:
        conditions.append(Review.rating == rating)
    if has_reports is not None:
        conditions.append(reports > 0 if has_reports else reports == 0)
    if search and search.strip():
        conditions.append(Review.comment.ilike(f"%{search.strip()}%"))

    total = await session.scalar(select(func.count(Review.id)).where(*conditions))
    order = (
        (reports.desc(), Review.created_at.desc(), Review.id.desc())
        if sort == "most_reported"
        else (Review.created_at.desc(), Review.id.desc())
    )
    rows = await session.execute(
        select(Review, reports).where(*conditions).order_by(*order).offset(skip).limit(limit)
    )
    return [(review, int(count or 0)) for review, count in rows.all()], int(total or 0)


async def establishment_names(session: AsyncSession, ids: set[int]) -> dict[int, tuple[str, str]]:
    """{id: (nombre, estado)} sin cargar menú, horarios ni imágenes."""
    if not ids:
        return {}
    rows = await session.execute(
        select(Establishment.id, Establishment.name, Establishment.status).where(Establishment.id.in_(ids))
    )
    return {row.id: (row.name, row.status) for row in rows.all()}


async def moderation_counts(session: AsyncSession) -> dict[str, int]:
    """Indicadores de moderación para el dashboard."""
    hidden = await session.scalar(select(func.count(Review.id)).where(Review.status == "HIDDEN"))
    blocked = await session.scalar(
        select(func.count(Review.id)).where(Review.comment_status == "BLOCKED")
    ) or 0
    blocked_replies = await session.scalar(
        select(func.count(ReviewReply.id)).where(ReviewReply.comment_status == "BLOCKED")
    ) or 0
    flagged = await session.scalar(
        select(func.count(Review.id)).where(
            or_(
                Review.flagged_for_review.is_(True),
                select(ReviewReply.id)
                .where(and_(ReviewReply.review_id == Review.id, ReviewReply.flagged_for_review.is_(True)))
                .exists(),
            )
        )
    )
    open_reports = await session.scalar(select(func.count(Report.id)).where(Report.status == "OPEN"))
    return {
        "hidden_reviews": int(hidden or 0),
        "blocked_comments": int(blocked) + int(blocked_replies),
        "flagged_for_review": int(flagged or 0),
        "open_reports": int(open_reports or 0),
    }


# --- Conversión a esquemas del admin --------------------------------------------------------------


def to_admin_review(review: Review, open_reports: int, establishments: dict[int, tuple[str, str]]) -> "AdminReviewItem":
    """Reseña vista por el admin: SIEMPRE con el texto original (también el de la respuesta)."""
    from app.schemas.admin import AdminReplyItem, AdminReviewAuthor, AdminReviewEstablishment, AdminReviewItem
    from app.schemas.review import ReviewImageResponse
    from app.services.review_service import display_name

    name, status = establishments.get(review.establishment_id, ("", ""))
    reply = review.reply
    author = review.author
    return AdminReviewItem(
        id=review.id,
        establishment=AdminReviewEstablishment(id=review.establishment_id, name=name, status=status),
        author=AdminReviewAuthor(
            id=author.id,
            display_name=display_name(author),
            full_name=author.full_name,
            email=author.email,
            status=author.status,
            picture=author.picture,
        ),
        rating=review.rating,
        comment=review.comment,
        status=review.status,
        comment_status=review.comment_status,
        moderation_category=review.moderation_category,
        moderation_reason=review.moderation_reason,
        flagged_for_review=review.flagged_for_review,
        created_at=ensure_utc(review.created_at),
        edited_at=ensure_utc(review.edited_at) if review.edited_at else None,
        images=[ReviewImageResponse.model_validate(image) for image in review.images],
        reply=(
            AdminReplyItem(
                id=reply.id,
                comment=reply.comment,
                comment_status=reply.comment_status,
                moderation_category=reply.moderation_category,
                moderation_reason=reply.moderation_reason,
                flagged_for_review=reply.flagged_for_review,
                created_at=ensure_utc(reply.created_at),
                updated_at=ensure_utc(reply.updated_at),
            )
            if reply is not None
            else None
        ),
        open_reports_count=open_reports,
    )


async def admin_review_items(session: AsyncSession, rows: list[tuple[Review, int]]) -> list["AdminReviewItem"]:
    names = await establishment_names(session, {review.establishment_id for review, _ in rows})
    return [to_admin_review(review, count, names) for review, count in rows]


async def admin_review_item(session: AsyncSession, review_id: int) -> "AdminReviewItem":
    """Recarga la reseña tras una acción (con su conteo de reportes abiertos)."""
    review = await get_review(session, review_id)
    count = await session.scalar(
        select(func.count(Report.id)).where(
            Report.status == "OPEN", Report.target_type == "REVIEW", Report.target_id == review.id
        )
    )
    return (await admin_review_items(session, [(review, int(count or 0))]))[0]


def to_moderation_action_item(entry: ModerationAction, admin: User | None) -> "ModerationActionItem":
    from app.schemas.admin import ModerationActionItem

    return ModerationActionItem(
        id=entry.id,
        admin_id=entry.admin_id,
        admin_name=admin.full_name if admin is not None else None,
        admin_email=admin.email if admin is not None else None,
        action=entry.action,
        target_type=entry.target_type,
        target_id=entry.target_id,
        reason=entry.reason,
        details=entry.details,
        created_at=ensure_utc(entry.created_at),
    )
