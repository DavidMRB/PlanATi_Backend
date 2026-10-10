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


async def send_phone_code(session: AsyncSession, user: User, phone_number: str) -> None:
    if user.phone_verified:
        raise PhoneVerificationError("El teléfono ya está verificado")
    normalized_phone = normalize_colombian_phone(phone_number)
    existing_user = await session.scalar(
        select(User).where(User.phone_number == normalized_phone, User.id != user.id)
    )
    if existing_user is not None:
        raise PhoneVerificationError("El número de teléfono ya está asociado a otra cuenta")

    now = datetime.now(timezone.utc)
    latest = await session.scalar(
        select(PhoneVerificationCode)
        .where(PhoneVerificationCode.user_id == user.id)
        .order_by(PhoneVerificationCode.created_at.desc())
    )
    if latest and latest.created_at and (now - latest.created_at).total_seconds() < settings.otp_resend_cooldown_seconds:
        raise PhoneVerificationError("Demasiadas solicitudes. Intenta nuevamente más tarde")

    code = f"{secrets.randbelow(1_000_000):06d}"
    verification = PhoneVerificationCode(
        user_id=user.id,
        phone_number=normalized_phone,
        code_hash=_hash_code(code),
        expires_at=now + timedelta(seconds=settings.otp_expiration_seconds),
    )
    session.add(verification)
    user.phone_number = normalized_phone
    user.status = "PENDING_PHONE"
    await session.commit()
    await get_sms_provider(settings.sms_provider).send_verification_code(normalized_phone, code)


async def verify_phone_code(
    session: AsyncSession, user: User, phone_number: str, code: str
) -> str:
    normalized_phone = normalize_colombian_phone(phone_number)
    verification = await session.scalar(
        select(PhoneVerificationCode)
        .where(
            PhoneVerificationCode.user_id == user.id,
            PhoneVerificationCode.phone_number == normalized_phone,
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

    verification.verified_at = now
    user.phone_number = normalized_phone
    user.phone_verified = True
    user.status = "ACTIVE"
    await session.commit()
    await session.refresh(user)
    return create_access_token(str(user.id))
