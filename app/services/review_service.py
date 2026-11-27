"""Reseñas de usuarios (plan de la fase 2, sección 7.2).

Reglas principales:
- Solo reseñan las cuentas `user` activas con teléfono verificado, en establecimientos `APPROVED`
  de los que no son dueñas, una vez por establecimiento y hasta `REVIEWS_PER_DAY_LIMIT` al día.
- Cada cambio de reseña recalcula los agregados del establecimiento en la misma transacción.
- `to_public_review` / `to_public_reply` son la ÚNICA salida pública de reseñas y respuestas: nunca
  devuelven el texto de un comentario bloqueado. `to_my_review` es la vista del autor.
"""

from collections.abc import Iterable
from datetime import datetime
from typing import Any, Literal

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.time import ensure_utc, local_day_start, utcnow
from app.models.establishment import Establishment
from app.models.notification import NotificationType
from app.models.review import (
    BLOCKED_COMMENT_NOTICE,
    BLOCKED_REPLY_NOTICE,
    Review,
    ReviewImage,
    ReviewReply,
)
from app.models.user import User
from app.schemas.review import (
    MyReview,
    ReviewAuthor,
    ReviewBlockReason,
    ReviewEstablishmentSummary,
    ReviewImageResponse,
    ReviewPublic,
    ReviewReplyPublic,
    ReviewSort,
)
from app.services.notification_service import notify
from app.services.rating_service import recalculate_establishment_rating

RECENT_REVIEWS_LIMIT = 3

BLOCK_MESSAGES: dict[str, str] = {
    "LOGIN_REQUIRED": "Inicia sesión para dejar tu reseña.",
    "SUSPENDED": "Tu cuenta está suspendida y no puede publicar reseñas.",
    "ROLE_NOT_ALLOWED": "Solo las cuentas de usuario pueden publicar reseñas.",
    "PHONE_NOT_VERIFIED": "Debes completar la verificación telefónica para publicar reseñas.",
    "OWNER": "No puedes reseñar tu propio establecimiento.",
    "ALREADY_REVIEWED": "Ya reseñaste este lugar. Puedes editar tu reseña.",
}


# --- Errores de dominio (app/main.py los convierte en {"detail", ...extra}) ---------------------


class ReviewError(Exception):
    status_code = 400

    def __init__(self, detail: str, **extra: Any) -> None:
        self.detail = detail
        self.extra = extra
        super().__init__(detail)


class ReviewNotFoundError(ReviewError):
    status_code = 404


class ReviewForbiddenError(ReviewError):
    status_code = 403


class ReviewConflictError(ReviewError):
    status_code = 409


class ReviewRateLimitError(ReviewError):
    status_code = 429


# --- Conversión a esquemas ---------------------------------------------------------------------


def display_name(user: User) -> str:
    """Apodo o "Primer nombre + inicial del apellido". Nunca email, teléfono ni nombre completo."""
    if user.nickname and user.nickname.strip():
        return user.nickname.strip()
    parts = (user.full_name or "").split()
    if not parts:
        return "Usuario de PlanATi"
    if len(parts) == 1:
        return parts[0]
    return f"{parts[0]} {parts[-1][0].upper()}."


def to_review_author(user: User) -> ReviewAuthor:
    return ReviewAuthor(id=user.id, display_name=display_name(user), picture=user.picture)


def to_public_reply(reply: ReviewReply | None) -> ReviewReplyPublic | None:
    if reply is None:
        return None
    blocked = reply.comment_status == "BLOCKED"
    return ReviewReplyPublic(
        id=reply.id,
        created_at=ensure_utc(reply.created_at),
        updated_at=ensure_utc(reply.updated_at),
        comment=None if blocked else reply.comment,
        comment_blocked=blocked,
        moderation_notice=BLOCKED_REPLY_NOTICE if blocked else None,
    )


def _public_fields(review: Review) -> dict[str, Any]:
    blocked = review.comment_status == "BLOCKED"
    return {
        "id": review.id,
        "establishment_id": review.establishment_id,
        "rating": review.rating,
        "comment": None if blocked else review.comment,
        "comment_blocked": blocked,
        "moderation_notice": BLOCKED_COMMENT_NOTICE if blocked else None,
        "created_at": ensure_utc(review.created_at),
        "edited_at": ensure_utc(review.edited_at) if review.edited_at else None,
        "status": review.status,
        "author": to_review_author(review.author),
        "images": [ReviewImageResponse.model_validate(image) for image in review.images],
        "reply": to_public_reply(review.reply),
    }


def to_public_review(review: Review) -> ReviewPublic:
    """Forma pública (y del panel del establecimiento): sin texto si el comentario está bloqueado."""
    return ReviewPublic(**_public_fields(review))


def to_my_review(review: Review, establishment: ReviewEstablishmentSummary) -> MyReview:
    """Vista del autor: su texto original aunque esté bloqueado, con el estado de moderación."""
    fields = _public_fields(review)
    fields["comment"] = review.comment
    return MyReview(
        **fields,
        comment_status=review.comment_status,
        moderation_category=review.moderation_category,
        moderation_reason=review.moderation_reason,
        flagged_for_review=review.flagged_for_review,
        establishment=establishment,
    )


def establishment_summary(establishment: Establishment) -> ReviewEstablishmentSummary:
    return ReviewEstablishmentSummary(
        id=establishment.id, name=establishment.name, profile_image_url=establishment.profile_image_url
    )


# --- Quién puede reseñar ----------------------------------------------------------------------


async def find_user_review(session: AsyncSession, user_id: int, establishment_id: int) -> Review | None:
    return await session.scalar(
        select(Review).where(Review.user_id == user_id, Review.establishment_id == establishment_id)
    )


def account_block_reason(user: User | None) -> ReviewBlockReason | None:
    """Motivos que dependen solo de la cuenta (rol, estado, teléfono)."""
    if user is None:
        return "LOGIN_REQUIRED"
    if user.status == "SUSPENDED":
        return "SUSPENDED"
    if user.role != "user":
        return "ROLE_NOT_ALLOWED"
    if not user.phone_verified or user.status != "ACTIVE":
        return "PHONE_NOT_VERIFIED"
    return None


async def check_can_review(
    session: AsyncSession,
    user: User | None,
    establishment: Establishment,
    existing: Review | None = None,
) -> ReviewBlockReason | None:
    """None si `user` puede reseñar `establishment`; si no, el motivo (`viewer_review_block`).

    No incluye el límite diario (se informa con 429 al publicar) ni el estado del establecimiento:
    un local no aprobado responde 404 antes de llegar aquí.
    """
    reason = account_block_reason(user)
    if reason is not None:
        return reason
    assert user is not None
    if establishment.owner_id == user.id:
        return "OWNER"
    if existing is None:
        existing = await find_user_review(session, user.id, establishment.id)
    if existing is not None:
        return "ALREADY_REVIEWED"
    return None


async def get_reviewable_establishment(session: AsyncSession, establishment_id: int) -> Establishment:
    establishment = await session.get(Establishment, establishment_id)
    if establishment is None or establishment.status != "APPROVED":
        raise ReviewNotFoundError("Establecimiento no encontrado")
    return establishment


async def _ensure_daily_limit(session: AsyncSession, user_id: int, now: datetime) -> None:
    created_today = await session.scalar(
        select(func.count(Review.id)).where(Review.user_id == user_id, Review.created_at >= local_day_start(now))
    )
    if int(created_today or 0) >= settings.reviews_per_day_limit:
        raise ReviewRateLimitError("Alcanzaste el límite diario de reseñas. Inténtalo de nuevo mañana.")


# --- Crear, editar y eliminar -----------------------------------------------------------------


def _image_rows(urls: Iterable[str]) -> list[ReviewImage]:
    return [ReviewImage(image_url=url, display_order=order) for order, url in enumerate(urls)]


async def _load_review(session: AsyncSession, review_id: int) -> Review | None:
    # populate_existing: la reseña puede estar en la sesión con relaciones ya cambiadas.
    return await session.scalar(
        select(Review).where(Review.id == review_id).execution_options(populate_existing=True)
    )


async def create_review(
    session: AsyncSession,
    user: User,
    establishment_id: int,
    rating: int,
    comment: str | None,
    image_urls: list[str],
    *,
    now: datetime | None = None,
) -> Review:
    now = ensure_utc(now or utcnow())
    user_id = user.id  # tras un rollback los objetos de la sesión quedan expirados
    establishment = await get_reviewable_establishment(session, establishment_id)
    existing = await find_user_review(session, user_id, establishment.id)
    reason = await check_can_review(session, user, establishment, existing)
    if reason == "ALREADY_REVIEWED":
        assert existing is not None
        raise ReviewConflictError(BLOCK_MESSAGES[reason], review_id=existing.id)
    if reason is not None:
        raise ReviewForbiddenError(BLOCK_MESSAGES[reason], code=reason)
    await _ensure_daily_limit(session, user.id, now)

    review = Review(
        user_id=user.id,
        establishment_id=establishment.id,
        rating=rating,
        comment=comment,
        images=_image_rows(image_urls),
    )
    session.add(review)
    try:
        await session.flush()
    except IntegrityError as error:
        # Dos peticiones simultáneas del mismo usuario: la restricción única decide.
        await session.rollback()
        existing = await find_user_review(session, user_id, establishment_id)
        raise ReviewConflictError(
            BLOCK_MESSAGES["ALREADY_REVIEWED"], review_id=existing.id if existing else None
        ) from error

    await recalculate_establishment_rating(session, establishment.id)
    stars = "estrella" if rating == 1 else "estrellas"
    await notify(
        session,
        establishment.owner_id,
        NotificationType.REVIEW_RECEIVED,
        f"Nueva reseña en {establishment.name}",
        f"{display_name(user)} calificó tu establecimiento con {rating} {stars}.",
        link="/restaurant/reviews",
        data={"review_id": review.id, "establishment_id": establishment.id},
    )
    review_id = review.id
    await session.commit()
    loaded = await _load_review(session, review_id)
    assert loaded is not None
    return loaded


async def get_own_review(session: AsyncSession, user: User, review_id: int) -> Review:
    """Reseña del usuario; una ajena o inexistente responde 404 (no se revela que existe)."""
    review = await session.scalar(select(Review).where(Review.id == review_id, Review.user_id == user.id))
    if review is None:
        raise ReviewNotFoundError("Reseña no encontrada")
    return review


async def update_review(
    session: AsyncSession,
    user: User,
    review_id: int,
    changes: dict[str, Any],
    *,
    now: datetime | None = None,
) -> Review:
    """`changes` = campos enviados (`model_dump(exclude_unset=True)` de `ReviewUpdate`)."""
    review = await get_own_review(session, user, review_id)
    if review.status == "HIDDEN":
        raise ReviewForbiddenError("Esta reseña fue ocultada por moderación y no puede editarse.", code="HIDDEN")

    rating_changed = "rating" in changes and changes["rating"] != review.rating
    changed = rating_changed
    if rating_changed:
        review.rating = changes["rating"]
    if "comment" in changes and changes["comment"] != review.comment:
        changed = True
        review.comment = changes["comment"]
        if review.comment_status == "BLOCKED":
            # El texto nuevo se guarda, pero sigue bloqueado hasta que un admin lo revise.
            review.flagged_for_review = True
    if changes.get("image_urls") is not None:
        if [image.image_url for image in review.images] != changes["image_urls"]:
            changed = True
            review.images.clear()
            await session.flush()
            review.images.extend(_image_rows(changes["image_urls"]))

    if changed:
        review.edited_at = ensure_utc(now or utcnow())
    await session.flush()
    if rating_changed:
        await recalculate_establishment_rating(session, review.establishment_id)
    await session.commit()
    loaded = await _load_review(session, review.id)
    assert loaded is not None
    return loaded


async def delete_review(session: AsyncSession, user: User, review_id: int) -> None:
    """Borrado físico por su autor (es su contenido) y recálculo de los agregados."""
    review = await get_own_review(session, user, review_id)
    establishment_id = review.establishment_id
    await session.delete(review)
    await session.flush()
    await recalculate_establishment_rating(session, establishment_id)
    await session.commit()


# --- Consultas --------------------------------------------------------------------------------

_SORTS: dict[str, tuple[Any, ...]] = {
    "recent": (Review.created_at.desc(), Review.id.desc()),
    "rating_desc": (Review.rating.desc(), Review.created_at.desc(), Review.id.desc()),
    "rating_asc": (Review.rating.asc(), Review.created_at.desc(), Review.id.desc()),
}


def _visible_reviews(establishment_id: int) -> Select:
    return select(Review).where(Review.establishment_id == establishment_id, Review.status == "VISIBLE")


async def list_reviews_for_establishment(
    session: AsyncSession,
    establishment_id: int,
    *,
    sort: ReviewSort = "recent",
    rating: int | None = None,
    with_photos: bool = False,
    skip: int = 0,
    limit: int = 10,
) -> tuple[list[Review], int]:
    """Reseñas VISIBLE de un establecimiento APPROVED (404 si no lo es). Devuelve (página, total)."""
    await get_reviewable_establishment(session, establishment_id)
    query = _visible_reviews(establishment_id)
    if rating is not None:
        query = query.where(Review.rating == rating)
    if with_photos:
        query = query.where(Review.images.any())
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(query.order_by(*_SORTS[sort]).offset(skip).limit(limit))
    return list(rows.all()), int(total or 0)


async def recent_reviews(session: AsyncSession, establishment_id: int, limit: int = RECENT_REVIEWS_LIMIT) -> list[Review]:
    rows = await session.scalars(_visible_reviews(establishment_id).order_by(*_SORTS["recent"]).limit(limit))
    return list(rows.all())


async def list_my_reviews(session: AsyncSession, user: User, *, skip: int = 0, limit: int = 10) -> tuple[list[MyReview], int]:
    """Todas las reseñas del usuario, incluidas las ocultas por moderación."""
    conditions = [Review.user_id == user.id]
    total = await session.scalar(select(func.count(Review.id)).where(*conditions))
    reviews = list(
        (
            await session.scalars(
                select(Review).where(*conditions).order_by(*_SORTS["recent"]).offset(skip).limit(limit)
            )
        ).all()
    )
    # Solo id, nombre e imagen: sin cargar el menú, los horarios ni las imágenes de cada local.
    summaries = {
        row.id: ReviewEstablishmentSummary(id=row.id, name=row.name, profile_image_url=row.profile_image_url)
        for row in (
            await session.execute(
                select(Establishment.id, Establishment.name, Establishment.profile_image_url).where(
                    Establishment.id.in_({review.establishment_id for review in reviews})
                )
            )
        ).all()
    }
    return [to_my_review(review, summaries[review.establishment_id]) for review in reviews], int(total or 0)


# --- Rutas legadas (deprecated) ---------------------------------------------------------------


async def add_review_image(session: AsyncSession, user: User, review_id: int, image_url: str) -> ReviewImage:
    review = await get_own_review(session, user, review_id)
    if review.status == "HIDDEN":
        raise ReviewForbiddenError("Esta reseña fue ocultada por moderación y no puede editarse.", code="HIDDEN")
    current = [image.image_url for image in review.images]
    if image_url in current:
        raise ReviewError("La imagen ya está en la reseña.")
    if len(current) >= settings.review_max_images:
        raise ReviewError(f"Puedes adjuntar como máximo {settings.review_max_images} imágenes.")
    image = ReviewImage(review_id=review.id, image_url=image_url, display_order=len(current))
    session.add(image)
    review.edited_at = utcnow()
    await session.commit()
    await session.refresh(image)
    return image


async def upsert_reply(
    session: AsyncSession,
    establishment: Establishment,
    review_id: int,
    comment: str,
) -> tuple[Review, bool]:
    """Crea o actualiza la respuesta del establecimiento a una de SUS reseñas visibles (idempotente).

    Devuelve (reseña con su respuesta, creada). Una reseña de otro local o no visible → 404.
    Si la respuesta estaba bloqueada por moderación, el texto nuevo se guarda pero sigue bloqueada y
    queda `flagged_for_review`. Se notifica al autor solo la primera vez que se responde la reseña.
    """
    review = await session.scalar(
        select(Review).where(
            Review.id == review_id, Review.establishment_id == establishment.id, Review.status == "VISIBLE"
        )
    )
    if review is None:
        raise ReviewNotFoundError("Reseña no encontrada")
    reply = review.reply
    created = reply is None
    if reply is None:
        session.add(ReviewReply(review_id=review.id, establishment_id=establishment.id, comment=comment))
        await notify(
            session,
            review.user_id,
            NotificationType.REVIEW_REPLIED,
            f"{establishment.name} respondió tu reseña",
            "Entra para ver la respuesta del establecimiento.",
            link=f"/establishments/{establishment.id}#review-{review.id}",
            data={"review_id": review.id, "establishment_id": establishment.id},
            # Si el local borra su respuesta y vuelve a responder, el autor no recibe otro aviso.
            dedupe_key=f"review-replied:{review.id}",
        )
    elif reply.comment != comment:
        reply.comment = comment
        reply.updated_at = utcnow()
        if reply.comment_status == "BLOCKED":
            reply.flagged_for_review = True
    await session.commit()
    loaded = await _load_review(session, review.id)
    assert loaded is not None
    return loaded, created


async def delete_reply(session: AsyncSession, establishment: Establishment, review_id: int) -> None:
    """Borra la respuesta del establecimiento a una de sus reseñas; 404 si no la hay."""
    reply = await session.scalar(
        select(ReviewReply)
        .join(Review, Review.id == ReviewReply.review_id)
        .where(ReviewReply.review_id == review_id, Review.establishment_id == establishment.id)
    )
    if reply is None:
        raise ReviewNotFoundError("Respuesta no encontrada")
    await session.delete(reply)
    await session.commit()


# --- Panel del establecimiento ----------------------------------------------------------------

ReplyFilter = Literal["all", "unanswered", "answered"]
_PANEL_SORTS = {"recent": _SORTS["recent"], "rating_asc": _SORTS["rating_asc"]}


def _has_reply() -> Any:
    return select(ReviewReply.id).where(ReviewReply.review_id == Review.id).exists()


async def list_reviews_for_owner(
    session: AsyncSession,
    establishment: Establishment,
    *,
    reply_status: ReplyFilter = "all",
    rating: int | None = None,
    sort: Literal["recent", "rating_asc"] = "recent",
    skip: int = 0,
    limit: int | None = 10,
) -> tuple[list[Review], int]:
    """Reseñas VISIBLE del local del dueño (sin exigir que esté APPROVED: eso lo hace la ruta)."""
    query = _visible_reviews(establishment.id)
    if reply_status == "unanswered":
        query = query.where(~_has_reply())
    elif reply_status == "answered":
        query = query.where(_has_reply())
    if rating is not None:
        query = query.where(Review.rating == rating)
    total = await session.scalar(select(func.count()).select_from(query.subquery()))
    rows = await session.scalars(query.order_by(*_PANEL_SORTS[sort]).offset(skip).limit(limit))
    return list(rows.all()), int(total or 0)


async def reply_stats(session: AsyncSession, establishment_id: int) -> tuple[int, float | None]:
    """(reseñas visibles sin responder, proporción respondida 0..1 o None si no hay reseñas)."""
    visible, answered = (
        await session.execute(
            select(func.count(Review.id), func.count(ReviewReply.id))
            .select_from(Review)
            .outerjoin(ReviewReply, ReviewReply.review_id == Review.id)
            .where(Review.establishment_id == establishment_id, Review.status == "VISIBLE")
        )
    ).one()
    visible, answered = int(visible or 0), int(answered or 0)
    return visible - answered, (round(answered / visible, 2) if visible else None)
