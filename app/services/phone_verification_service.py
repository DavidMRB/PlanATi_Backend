# Verificación del teléfono con código SMS (OTP): normaliza el número, envía el código y lo valida.
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token
from app.integrations.sms import get_sms_provider
from app.models.phone_verification import PhoneVerificationCode
from app.models.user import User


class PhoneVerificationError(ValueError):
    pass


# GUIA #7 TEMA: Cadenas, listas, tuplas y diccionarios -> índices y segmentos de cadena: se dejan solo los dígitos, `digits[2:]` quita
# el indicativo 57, `len()` valida la longitud y una f-string arma el resultado ('+573001234567').
# GUIA #10 TEMA: Subalgoritmos (funciones, procedimientos y modularización) -> función reutilizada en el registro y en el cambio de teléfono.
def normalize_colombian_phone(phone_number: str) -> str:
    digits = re.sub(r"[^\d]", "", phone_number)
    if digits.startswith("57"):
        digits = digits[2:]
    if len(digits) != 10 or not digits.startswith("3"):
        raise PhoneVerificationError("Número de teléfono inválido")
    return f"+57{digits}"


async def set_phone_number(session: AsyncSession, user: User, phone_number: str) -> None:
    normalized_phone = normalize_colombian_phone(phone_number)
    existing_user = await session.scalar(
        select(User).where(User.phone_number == normalized_phone, User.id != user.id)
    )
    if existing_user is not None:
        raise PhoneVerificationError("El número de teléfono ya está asociado a otra cuenta")
    if user.phone_number == normalized_phone:
        return
    user.phone_number = normalized_phone
    user.phone_verified = False
    user.status = "PENDING_PHONE"
    await session.commit()
    await session.refresh(user)


def _hash_code(code: str) -> str:
    return hmac.new(
        settings.secret_key.encode(), code.encode(), hashlib.sha256
    ).hexdigest()


async def _ensure_phone_available(session: AsyncSession, user: User, normalized_phone: str) -> None:
    existing_user = await session.scalar(
        select(User).where(User.phone_number == normalized_phone, User.id != user.id)
    )
    if existing_user is not None:
        raise PhoneVerificationError("El número de teléfono ya está asociado a otra cuenta")


async def _issue_code(
    session: AsyncSession, user: User, normalized_phone: str, purpose: str = "VERIFY_PHONE"
) -> str:
    now = datetime.now(timezone.utc)
    latest = await session.scalar(
        select(PhoneVerificationCode)
        .where(PhoneVerificationCode.user_id == user.id)
        .order_by(PhoneVerificationCode.created_at.desc())
    )
    if latest and latest.created_at:
        latest_created_at = latest.created_at
        if latest_created_at.tzinfo is None:
            latest_created_at = latest_created_at.replace(tzinfo=timezone.utc)
        if (now - latest_created_at).total_seconds() < settings.otp_resend_cooldown_seconds:
            raise PhoneVerificationError("Demasiadas solicitudes. Intenta nuevamente más tarde")

    code = f"{secrets.randbelow(1_000_000):06d}"
    session.add(
        PhoneVerificationCode(
            user_id=user.id,
            phone_number=normalized_phone,
            purpose=purpose,
            code_hash=_hash_code(code),
            expires_at=now + timedelta(seconds=settings.otp_expiration_seconds),
        )
    )
    return code


async def send_phone_code(session: AsyncSession, user: User, phone_number: str) -> None:
    if user.phone_verified:
        raise PhoneVerificationError("El teléfono ya está verificado")
    normalized_phone = normalize_colombian_phone(phone_number)
    await _ensure_phone_available(session, user, normalized_phone)

    code = await _issue_code(session, user, normalized_phone)
    user.phone_number = normalized_phone
    user.status = "PENDING_PHONE"
    await session.commit()
    await get_sms_provider(settings.sms_provider).send_verification_code(normalized_phone, code)


async def send_phone_change_code(session: AsyncSession, user: User, phone_number: str) -> None:
    """Envía el OTP al número nuevo sin tocar la cuenta: el número actual sigue vigente hasta verificarlo."""
    normalized_phone = normalize_colombian_phone(phone_number)
    if user.phone_verified and user.phone_number == normalized_phone:
        raise PhoneVerificationError("Ese ya es tu número verificado")
    await _ensure_phone_available(session, user, normalized_phone)

    code = await _issue_code(session, user, normalized_phone)
    await session.commit()
    await get_sms_provider(settings.sms_provider).send_verification_code(normalized_phone, code)


async def _check_code(
    session: AsyncSession, user: User, normalized_phone: str, code: str, purpose: str
) -> PhoneVerificationCode:
    """Comprueba el último código pendiente de ese propósito. Un intento fallido se guarda (commit)."""
    verification = await session.scalar(
        select(PhoneVerificationCode)
        .where(
            PhoneVerificationCode.user_id == user.id,
            PhoneVerificationCode.phone_number == normalized_phone,
            PhoneVerificationCode.purpose == purpose,
            PhoneVerificationCode.verified_at.is_(None),
        )
        .order_by(PhoneVerificationCode.created_at.desc())
    )
    if verification is None:
        raise PhoneVerificationError("Código de verificación inválido")
    now = datetime.now(timezone.utc)
    expires_at = verification.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= now:
        raise PhoneVerificationError("El código de verificación expiró")
    if verification.attempts >= settings.otp_max_attempts:
        raise PhoneVerificationError("Se superó el máximo de intentos")

    verification.attempts += 1
    if not hmac.compare_digest(verification.code_hash, _hash_code(code)):
        await session.commit()
        raise PhoneVerificationError("Código de verificación inválido")
    return verification


async def send_account_deletion_code(session: AsyncSession, user: User) -> None:
    """Envía al teléfono verificado el código que confirma la eliminación de la cuenta (B8)."""
    if not user.phone_verified or not user.phone_number:
        raise PhoneVerificationError("Tu cuenta no tiene un teléfono verificado. Confirma con tu contraseña.")
    code = await _issue_code(session, user, user.phone_number, purpose="DELETE_ACCOUNT")
    await session.commit()
    await get_sms_provider(settings.sms_provider).send_verification_code(user.phone_number, code)


async def check_account_deletion_code(session: AsyncSession, user: User, code: str) -> None:
    """Valida y consume (sin commit) el código de eliminación; la ruta hace el commit con el borrado."""
    if not user.phone_verified or not user.phone_number:
        raise PhoneVerificationError("Código de verificación inválido")
    verification = await _check_code(session, user, user.phone_number, code, "DELETE_ACCOUNT")
    verification.verified_at = datetime.now(timezone.utc)


async def verify_phone_code(
    session: AsyncSession, user: User, phone_number: str, code: str
) -> str:
    normalized_phone = normalize_colombian_phone(phone_number)
    verification = await _check_code(session, user, normalized_phone, code, "VERIFY_PHONE")
    now = datetime.now(timezone.utc)

    # Otra cuenta pudo adoptar el número mientras el código estaba pendiente.
    await _ensure_phone_available(session, user, normalized_phone)
    verification.verified_at = now
    user.phone_number = normalized_phone
    user.phone_verified = True
    user.status = "ACTIVE"
    await session.commit()
    await session.refresh(user)
    return create_access_token(str(user.id))
