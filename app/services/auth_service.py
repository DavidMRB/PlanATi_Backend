import secrets

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password, verify_password
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
            user.picture = identity.get("picture") or user.picture
        await session.commit()
        await session.refresh(user)
    else:
        email = identity.get("email")
        name = identity.get("name")
        picture = identity.get("picture")
        if isinstance(email, str) and email:
            user.email = email
        if isinstance(name, str) and name:
            user.full_name = name
            if not user.nickname:
                user.nickname = name
        if isinstance(picture, str) and picture:
            user.picture = picture
        await session.commit()
    return user, issue_access_token(user)
