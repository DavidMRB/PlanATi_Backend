import hashlib
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import create_access_token, hash_password, verify_password
from app.models.establishment import Establishment
from app.models.oauth_login_code import OAuthLoginCode
from app.models.user import User
from app.services.phone_verification_service import normalize_colombian_phone


async def register_user(
    session: AsyncSession,
    full_name: str,
    nickname: str | None,
    email: str,
    password: str,
    phone_number: str,
) -> User:
    normalized_email = email.strip().lower()
    normalized_phone = normalize_colombian_phone(phone_number)
    existing_user = await session.scalar(select(User).where(User.email == normalized_email))
    if existing_user is not None:
        raise ValueError("El correo ya esta registrado")
    existing_phone = await session.scalar(select(User).where(User.phone_number == normalized_phone))
    if existing_phone is not None:
        raise ValueError("El número de teléfono ya está asociado a otra cuenta")

    user = User(
        full_name=full_name.strip(),
        nickname=nickname.strip() if nickname else None,
        email=normalized_email,
        phone_number=normalized_phone,
        password_hash=hash_password(password),
        phone_verified=False,
        status="PENDING_PHONE",
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def register_restaurant(
    session: AsyncSession,
    *,
    account_email: str,
    password: str,
    manager_name: str,
    establishment_name: str,
    category: str,
    address: str,
    establishment_phone: str,
    contact_email: str,
    description: str,
    profile_image_url: str | None,
    banner_image_url: str | None,
) -> tuple[User, Establishment]:
    normalized_email = account_email.strip().lower()
    existing_user = await session.scalar(select(User).where(User.email == normalized_email))
    if existing_user is not None:
        raise ValueError("El correo de la cuenta ya está registrado")

    # Los restaurantes no pasan por OTP: su acceso queda gobernado por la aprobación del establecimiento.
    user = User(
        full_name=manager_name.strip(),
        email=normalized_email,
        password_hash=hash_password(password),
        role="restaurant",
        phone_verified=True,
        status="ACTIVE",
    )
    establishment = Establishment(
        owner=user,
        name=establishment_name.strip(),
        category=category.strip(),
        address=address.strip(),
        description=description.strip(),
        phone=establishment_phone,
        contact_email=contact_email.strip().lower(),
        manager_name=manager_name.strip(),
        profile_image_url=profile_image_url,
        banner_image_url=banner_image_url,
        status="PENDING",
    )
    session.add_all([user, establishment])
    await session.commit()
    await session.refresh(user)
    await session.refresh(establishment)
    return user, establishment


async def get_owned_establishment_status(session: AsyncSession, user: User) -> str | None:
    if user.role != "restaurant":
        return None
    return await session.scalar(
        select(Establishment.status).where(Establishment.owner_id == user.id).order_by(Establishment.id)
    )


async def authenticate_user(
    session: AsyncSession,
    email: str,
    password: str,
) -> User | None:
    normalized_email = email.strip().lower()
    user = await session.scalar(select(User).where(User.email == normalized_email))
    if user is None or not verify_password(password, user.password_hash):
        return None
    return user


def issue_access_token(user: User) -> str:
    return create_access_token(str(user.id))


async def issue_oauth_login_code(session: AsyncSession, user: User) -> str:
    raw_code = secrets.token_urlsafe(32)
    code_hash = hashlib.sha256(raw_code.encode("utf-8")).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.oauth_code_ttl_seconds)
    session.add(OAuthLoginCode(user_id=user.id, code_hash=code_hash, expires_at=expires_at))
    await session.commit()
    return raw_code


async def consume_oauth_login_code(session: AsyncSession, raw_code: str) -> User:
    normalized_code = raw_code.strip()
    if not normalized_code:
        raise ValueError("Código OAuth inválido")

    code_hash = hashlib.sha256(normalized_code.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    result = await session.execute(
        update(OAuthLoginCode)
        .where(
            OAuthLoginCode.code_hash == code_hash,
            OAuthLoginCode.expires_at > now,
            OAuthLoginCode.consumed_at.is_(None),
        )
        .values(consumed_at=now)
        .returning(OAuthLoginCode.user_id)
    )
    row = result.first()
    if row is None:
        raise ValueError("Código OAuth inválido o expirado")

    await session.commit()
    user = await session.get(User, row.user_id)
    if user is None:
        raise ValueError("Usuario asociado al código OAuth no encontrado")
    return user


async def authenticate_google_user(
    session: AsyncSession, identity: dict[str, str | bool | None]
) -> tuple[User, str]:
    google_sub = identity.get("google_sub")
    if not isinstance(google_sub, str) or not google_sub:
        raise ValueError("La identidad de Google no contiene sub")
    if identity.get("email_verified") is not True:
        raise ValueError("El correo de Google no está verificado")
    user = await session.scalar(select(User).where(User.google_sub == google_sub))
    if user is None:
        email = identity.get("email")
        name = identity.get("name")
        if not isinstance(email, str) or not isinstance(name, str) or not email or not name:
            raise ValueError("La identidad de Google no contiene los datos requeridos")
        user = await session.scalar(select(User).where(User.email == email.lower()))
        if user is None:
            user = User(
                google_sub=google_sub,
                email=email.lower(),
                full_name=name,
                nickname=name,
                picture=identity.get("picture") if isinstance(identity.get("picture"), str) else None,
                password_hash=hash_password(secrets.token_urlsafe(32)),
                phone_verified=False,
                status="PENDING_PHONE",
            )
            session.add(user)
        else:
            user.google_sub = google_sub
            if not user.nickname:
                user.nickname = name
            if not user.picture:
                user.picture = identity.get("picture") or None
        await session.commit()
        await session.refresh(user)
    else:
        email = identity.get("email")
        name = identity.get("name")
        picture = identity.get("picture")
        if isinstance(email, str) and email:
            user.email = email
        # Google solo completa lo que falta: lo que el usuario editó en Mi perfil no se sobrescribe al volver a entrar.
        if isinstance(name, str) and name:
            if not user.full_name:
                user.full_name = name
            if not user.nickname:
                user.nickname = name
        if isinstance(picture, str) and picture and not user.picture:
            user.picture = picture
        await session.commit()
    return user, issue_access_token(user)
