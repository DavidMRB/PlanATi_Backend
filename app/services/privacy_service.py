"""Privacidad y datos personales (Ley 1581 de 2012; plan de la fase 2, sección 7.9 y fase B8).

- **Consentimientos:** versiones vigentes en la configuración (`PRIVACY_POLICY_VERSION`, `TERMS_VERSION`).
  Cada aceptación inserta filas en `consents` (historial, prueba de la autorización) y copia la versión
  en `users` para comprobarla en cada petición sin consultas extra. No hay edad mínima (D10).
- **Exportación:** `export_user_data` arma el JSON de "mis datos".
- **Eliminación de la cuenta (D9):** se borra todo lo personal (reseñas con imágenes y respuestas,
  planes, favoritos, notificaciones, códigos) y se recalculan los promedios afectados. Para no romper
  la trazabilidad, la fila de `users` queda como una **lápida anonimizada** (`status=DELETED`, sin
  nombre, correo, teléfono, foto ni contraseña utilizable): así la bitácora de moderación, los
  reportes que hizo y el historial de consentimientos (sin IP ni user agent) siguen apuntando a un id
  válido, sin datos personales. La bitácora conserva ids, categorías y estados, pero se le quita el
  texto, las fotos y los mensajes del titular. Los reportes abiertos sobre su contenido se cierran.

Ninguna función hace commit salvo que se indique: la ruta hace un único `commit()`.
"""

import secrets
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import hash_password
from app.core.time import ensure_utc, utcnow
from app.models.establishment import Establishment
from app.models.favorite import Favorite
from app.models.moderation import ModerationAction
from app.models.notification import Notification
from app.models.oauth_login_code import OAuthLoginCode
from app.models.phone_verification import PhoneVerificationCode
from app.models.plan import Plan
from app.models.privacy import Consent
from app.models.report import Report
from app.models.review import Review, ReviewImage
from app.models.user import DELETED_USER_NAME, User
from app.services.moderation_service import jsonable, record_moderation_action
from app.services.rating_service import recalculate_establishment_rating

CONSENT_REQUIRED_DETAIL = "Debes aceptar la versión vigente de la política de datos y de los términos."
DELETED_EMAIL_DOMAIN = "eliminado.planati.invalid"
ACCOUNT_DELETED_NOTE = "Contenido eliminado: su autor eliminó la cuenta."
# Claves de `moderation_actions.details` que se conservan al eliminar la cuenta (no son datos personales).
_KEPT_LOG_KEYS = {
    "user_id",
    "establishment_id",
    "review_id",
    "rating",
    "status",
    "comment_status",
    "category",
    "previous_status",
    "new_status",
    "before",
    "after",
    "action",
    "report_ids",
}


# --- Errores de dominio (app/main.py los convierte en {"detail", ...extra}) ---------------------


class PrivacyError(Exception):
    status_code = 400

    def __init__(self, detail: str, **extra: Any) -> None:
        self.detail = detail
        self.extra = extra
        super().__init__(detail)


class ConsentRequiredError(PrivacyError):
    """La cuenta no ha aceptado las versiones vigentes: 403 `CONSENT_REQUIRED` en rutas protegidas."""

    status_code = 403

    def __init__(self, pending: list[str]) -> None:
        super().__init__(CONSENT_REQUIRED_DETAIL, code="CONSENT_REQUIRED", pending_consents=pending)


class ConsentVersionError(PrivacyError):
    status_code = 409

    def __init__(self) -> None:
        super().__init__(
            "La política de datos o los términos cambiaron. Revisa y acepta la versión vigente.",
            code="CONSENT_VERSION_OUTDATED",
            current_versions=current_versions(),
        )


class AccountDeletionError(PrivacyError):
    pass


class AccountDeletionForbiddenError(PrivacyError):
    status_code = 409


class DataExportRateLimitError(PrivacyError):
    status_code = 429


# --- Consentimientos ----------------------------------------------------------------------------


def current_versions() -> dict[str, str]:
    return {"privacy_policy": settings.privacy_policy_version, "terms": settings.terms_version}


def ensure_consents(user: User) -> None:
    pending = user.pending_consents
    if pending:
        raise ConsentRequiredError(pending)


def check_versions(privacy_policy_version: str, terms_version: str) -> None:
    if (
        privacy_policy_version.strip() != settings.privacy_policy_version
        or terms_version.strip() != settings.terms_version
    ):
        raise ConsentVersionError()


def _clip(value: str | None, length: int) -> str | None:
    if not value:
        return None
    return value[:length]


def record_consents(
    session: AsyncSession,
    user: User,
    channel: str,
    *,
    ip_address: str | None,
    user_agent: str | None,
    now: datetime | None = None,
) -> None:
    """Registra la aceptación de las versiones vigentes (ya validadas con `check_versions`). Sin commit.

    La cuenta ya debe tener id (en el registro, tras un `flush`).
    """
    now = now or utcnow()
    for document, version in (
        ("PRIVACY_POLICY", settings.privacy_policy_version),
        ("TERMS", settings.terms_version),
    ):
        consent = Consent(
            user_id=user.id,
            document=document,
            version=version,
            channel=channel,
            accepted_at=now,
            ip_address=_clip(ip_address, 45),
            user_agent=_clip(user_agent, 255),
        )
        session.add(consent)
    user.privacy_policy_version = settings.privacy_policy_version
    user.terms_version = settings.terms_version
    user.consents_updated_at = now


async def accept_current_consents(
    session: AsyncSession,
    user: User,
    privacy_policy_version: str,
    terms_version: str,
    *,
    ip_address: str | None,
    user_agent: str | None,
) -> None:
    """`POST /users/me/consents`. Idempotente si ya aceptó las vigentes. Sin commit."""
    check_versions(privacy_policy_version, terms_version)
    if not user.pending_consents:
        return
    has_history = await session.scalar(select(Consent.id).where(Consent.user_id == user.id).limit(1))
    # La cuenta de Google se crea en el callback, antes de ver las casillas: acepta al completar el perfil.
    channel = "GOOGLE_COMPLETE_PROFILE" if user.google_sub and has_history is None else "RE_ACCEPTANCE"
    record_consents(session, user, channel, ip_address=ip_address, user_agent=user_agent)


async def list_consents(session: AsyncSession, user_id: int) -> list[Consent]:
    return list(
        (
            await session.scalars(
                select(Consent).where(Consent.user_id == user_id).order_by(Consent.accepted_at.desc(), Consent.id.desc())
            )
        ).all()
    )


# --- Exportación --------------------------------------------------------------------------------


def _dt(value: datetime | None) -> str | None:
    return ensure_utc(value).isoformat() if value is not None else None


async def export_user_data(session: AsyncSession, user: User, *, now: datetime | None = None) -> dict[str, Any]:
    """Datos del titular (`GET /users/me/export`). Marca `last_data_export_at` (sin commit).

    Lanza `DataExportRateLimitError` (429) si pidió otra descarga hace menos de
    `DATA_EXPORT_COOLDOWN_MINUTES`.
    """
    now = now or utcnow()
    if user.last_data_export_at is not None:
        wait = ensure_utc(user.last_data_export_at) + timedelta(minutes=settings.data_export_cooldown_minutes) - now
        if wait.total_seconds() > 0:
            raise DataExportRateLimitError(
                "Ya descargaste tus datos hace poco. Intenta de nuevo más tarde.",
                retry_after_seconds=int(wait.total_seconds()) + 1,
            )

    reviews = (
        await session.scalars(select(Review).where(Review.user_id == user.id).order_by(Review.created_at, Review.id))
    ).all()
    plans = (await session.scalars(select(Plan).where(Plan.user_id == user.id).order_by(Plan.scheduled_at, Plan.id))).all()
    favorites = (
        await session.execute(
            select(Favorite, Establishment.name)
            .join(Establishment, Establishment.id == Favorite.establishment_id)
            .where(Favorite.user_id == user.id)
            .order_by(Favorite.created_at, Favorite.id)
        )
    ).all()
    reports = (
        await session.scalars(select(Report).where(Report.reporter_id == user.id).order_by(Report.created_at, Report.id))
    ).all()
    notifications = (
        await session.scalars(
            select(Notification)
            .where(Notification.user_id == user.id, Notification.created_at >= now - timedelta(days=90))
            .order_by(Notification.created_at, Notification.id)
        )
    ).all()
    establishment_ids = {review.establishment_id for review in reviews} | {plan.establishment_id for plan in plans}
    names = dict(
        (
            await session.execute(
                select(Establishment.id, Establishment.name).where(Establishment.id.in_(establishment_ids))
            )
        ).all()
    ) if establishment_ids else {}

    data: dict[str, Any] = {
        "generated_at": _dt(now),
        "profile": {
            "id": user.id,
            "full_name": user.full_name,
            "nickname": user.nickname,
            "email": user.email,
            "phone_number": user.phone_number,
            "phone_verified": user.phone_verified,
            "picture": user.picture,
            "role": user.role,
            "status": user.status,
            "google_account": user.google_sub is not None,
            "created_at": _dt(user.created_at),
            "privacy_policy_version": user.privacy_policy_version,
            "terms_version": user.terms_version,
        },
        "consents": [
            {
                "document": consent.document,
                "version": consent.version,
                "channel": consent.channel,
                "accepted_at": _dt(consent.accepted_at),
                "ip_address": consent.ip_address,
                "user_agent": consent.user_agent,
            }
            for consent in await list_consents(session, user.id)
        ],
        "reviews": [
            {
                "id": review.id,
                "establishment_id": review.establishment_id,
                "establishment_name": names.get(review.establishment_id),
                "rating": review.rating,
                # Texto original, también si un admin lo bloqueó.
                "comment": review.comment,
                "status": review.status,
                "comment_status": review.comment_status,
                "moderation_reason": review.moderation_reason,
                "images": [image.image_url for image in review.images],
                "reply": (
                    {"comment": review.reply.comment, "created_at": _dt(review.reply.created_at)}
                    if review.reply is not None and review.reply.comment_status == "VISIBLE"
                    else None
                ),
                "created_at": _dt(review.created_at),
                "edited_at": _dt(review.edited_at),
            }
            for review in reviews
        ],
        "plans": [
            {
                "id": plan.id,
                "establishment_id": plan.establishment_id,
                "establishment_name": names.get(plan.establishment_id),
                "title": plan.title,
                "scheduled_at": _dt(plan.scheduled_at),
                "party_size": plan.party_size,
                "notes": plan.notes,
                "status": plan.status,
                "reminder_minutes_before": plan.reminder_minutes_before,
                "total_amount": jsonable(plan.total_amount),
                "currency": plan.currency,
                "items": [
                    {
                        "name": item.name_snapshot,
                        "unit_price": jsonable(item.unit_price_snapshot),
                        "quantity": item.quantity,
                        "notes": item.notes,
                    }
                    for item in plan.items
                ],
                "created_at": _dt(plan.created_at),
            }
            for plan in plans
        ],
        "favorites": [
            {"establishment_id": favorite.establishment_id, "establishment_name": name, "created_at": _dt(favorite.created_at)}
            for favorite, name in favorites
        ],
        "reports": [
            {
                "id": report.id,
                "target_type": report.target_type,
                "target_id": report.target_id,
                "reason": report.reason,
                "details": report.details,
                "status": report.status,
                "created_at": _dt(report.created_at),
            }
            for report in reports
        ],
        "notifications_last_90_days": [
            {
                "type": notification.type,
                "title": notification.title,
                "body": notification.body,
                "read_at": _dt(notification.read_at),
                "created_at": _dt(notification.created_at),
            }
            for notification in notifications
        ],
    }
    user.last_data_export_at = now
    return data


# --- Eliminación de la cuenta -------------------------------------------------------------------


def ensure_can_self_delete(user: User) -> None:
    if user.role != "user":
        raise AccountDeletionForbiddenError(
            "Solicita la eliminación de tu cuenta a soporte.", code="SUPPORT_REQUIRED"
        )


def _redact(details: dict[str, Any] | None) -> dict[str, Any]:
    kept = {key: value for key, value in (details or {}).items() if key in _KEPT_LOG_KEYS}
    kept["redacted"] = "ACCOUNT_DELETED"
    return kept


async def _redact_moderation_log(
    session: AsyncSession, user_id: int, review_ids: set[int], image_ids: set[int]
) -> None:
    """Quita de la bitácora el texto, las fotos y los mensajes del titular; conserva ids y estados."""
    # Reseñas que un admin ya borró antes: su copia en DELETE_REVIEW lleva el user_id del autor.
    deleted_reviews = (
        await session.execute(
            select(ModerationAction.target_id, ModerationAction.details).where(
                ModerationAction.action == "DELETE_REVIEW", ModerationAction.target_type == "REVIEW"
            )
        )
    ).all()
    review_ids = review_ids | {
        target_id for target_id, details in deleted_reviews if (details or {}).get("user_id") == user_id
    }
    entries = (
        await session.scalars(
            select(ModerationAction).where(
                ModerationAction.target_type.in_(("REVIEW", "REVIEW_IMAGE", "USER"))
            )
        )
    ).all()
    for entry in entries:
        details = entry.details or {}
        concerns_user = (
            (entry.target_type == "REVIEW" and entry.target_id in review_ids)
            or (
                entry.target_type == "REVIEW_IMAGE"
                and (entry.target_id in image_ids or details.get("review_id") in review_ids)
            )
            or (entry.target_type == "USER" and entry.target_id == user_id)
        )
        if concerns_user and details.get("redacted") is None and entry.details is not None:
            entry.details = _redact(entry.details)


async def _close_reports_on_user_content(
    session: AsyncSession, user_id: int, review_ids: set[int], image_ids: set[int], now: datetime
) -> list[int]:
    conditions = [(Report.target_type == "USER") & (Report.target_id == user_id)]
    if review_ids:
        conditions.append((Report.target_type == "REVIEW") & Report.target_id.in_(review_ids))
    if image_ids:
        conditions.append((Report.target_type == "REVIEW_IMAGE") & Report.target_id.in_(image_ids))
    reports = (await session.scalars(select(Report).where(Report.status == "OPEN", or_(*conditions)))).all()
    for report in reports:
        report.status = "RESOLVED"
        report.resolution_note = ACCOUNT_DELETED_NOTE
        report.resolved_by_id = None
        report.resolved_at = now
    return [report.id for report in reports]


async def delete_account(session: AsyncSession, user: User, *, now: datetime | None = None) -> dict[str, int]:
    """Elimina la cuenta del titular en una sola transacción (sin commit). Devuelve los conteos.

    La identidad (contraseña o código SMS) ya debe estar comprobada por la ruta.
    """
    ensure_can_self_delete(user)
    now = now or utcnow()
    user_id = user.id

    reviews = list((await session.scalars(select(Review).where(Review.user_id == user_id))).all())
    review_ids = {review.id for review in reviews}
    image_ids = {image.id for review in reviews for image in review.images}
    affected_establishments = {review.establishment_id for review in reviews}

    await _redact_moderation_log(session, user_id, review_ids, image_ids)
    closed_reports = await _close_reports_on_user_content(session, user_id, review_ids, image_ids, now)

    # Borrado por el ORM (no en bloque) para que caigan imágenes y respuestas también en SQLite.
    for review in reviews:
        await session.delete(review)
    plans = list((await session.scalars(select(Plan).where(Plan.user_id == user_id))).all())
    for plan in plans:
        await session.delete(plan)
    favorites = await session.execute(delete(Favorite).where(Favorite.user_id == user_id))
    notifications = await session.execute(delete(Notification).where(Notification.user_id == user_id))
    await session.execute(delete(PhoneVerificationCode).where(PhoneVerificationCode.user_id == user_id))
    await session.execute(delete(OAuthLoginCode).where(OAuthLoginCode.user_id == user_id))
    await session.flush()
    for establishment_id in affected_establishments:
        await recalculate_establishment_rating(session, establishment_id)

    # Los consentimientos se conservan como prueba de la autorización, sin IP ni user agent.
    for consent in await list_consents(session, user_id):
        consent.ip_address = None
        consent.user_agent = None

    # Lápida anonimizada: libera el correo y el teléfono y deja la cuenta inutilizable.
    user.full_name = DELETED_USER_NAME
    user.nickname = None
    user.email = f"eliminado-{user_id}@{DELETED_EMAIL_DOMAIN}"
    user.google_sub = None
    user.picture = None
    user.phone_number = None
    user.phone_verified = False
    user.password_hash = hash_password(secrets.token_urlsafe(32))
    user.suspension_reason = None
    user.suspended_at = None
    user.last_data_export_at = None
    user.status = "DELETED"
    user.deleted_at = now

    counts = {
        "reviews": len(reviews),
        "plans": len(plans),
        "favorites": favorites.rowcount or 0,
        "notifications": notifications.rowcount or 0,
        "reports_closed": len(closed_reports),
    }
    await record_moderation_action(
        session,
        None,
        "DELETE_ACCOUNT",
        "USER",
        user_id,
        reason="Eliminación solicitada por el titular.",
        details={**counts, "establishment_ids": sorted(affected_establishments), "report_ids": closed_reports},
    )
    return counts
