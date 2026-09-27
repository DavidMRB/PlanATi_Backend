from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User


async def register_user(
    session: AsyncSession,
    full_name: str,
    email: str,
    password: str,
) -> User:
    normalized_email = email.strip().lower()
    existing_user = await session.scalar(select(User).where(User.email == normalized_email))
    if existing_user is not None:
        raise ValueError("El correo ya esta registrado")

    user = User(
        full_name=full_name.strip(),
        email=normalized_email,
        password_hash=hash_password(password),
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
