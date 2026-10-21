from collections.abc import AsyncGenerator

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import session_factory
from app.models.establishment import Establishment
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        yield session


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalido o expirado",
        headers={"WWW-Authenticate": "Bearer"},
    )

    token = None
    if credentials is not None:
        token = credentials.credentials
    if not token:
        token = request.cookies.get(settings.access_token_cookie_name)
    if not token:
        raise unauthorized

    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError, jwt.InvalidTokenError) as error:
        raise unauthorized from error

    user = await session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise unauthorized
    return user


async def get_optional_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> User | None:
    try:
        return await get_current_user(request, credentials, session)
    except HTTPException:
        return None


async def require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Se requieren permisos de administrador.",
        )
    if not current_user.phone_verified or current_user.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Debes completar la verificación telefónica.",
        )
    return current_user


async def require_active_user(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.phone_verified or current_user.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Debes completar la verificación telefónica.",
        )
    return current_user


class EstablishmentAccessError(Exception):
    """Acceso denegado al panel por el estado de aprobación; se responde 403 con el estado actual."""

    messages = {
        "PENDING": "Establecimiento en revisión",
        "REJECTED": "Establecimiento rechazado",
    }

    def __init__(self, establishment_status: str) -> None:
        self.status = establishment_status
        self.detail = self.messages.get(
            establishment_status,
            f"Establecimiento en estado '{establishment_status}'. No tiene acceso al panel de gestión.",
        )
        super().__init__(self.detail)


async def require_restaurant_user(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> tuple[User, Establishment]:
    if current_user.role != "restaurant":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido a cuentas de restaurante.",
        )
    # El establecimiento se resuelve siempre por propietario; nunca por un id enviado por el cliente.
    establishment = await session.scalar(
        select(Establishment).where(Establishment.owner_id == current_user.id).order_by(Establishment.id)
    )
    if establishment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No se encontró un establecimiento para esta cuenta.",
        )
    return current_user, establishment


async def require_approved_restaurant(
    data: tuple[User, Establishment] = Depends(require_restaurant_user),
) -> tuple[User, Establishment]:
    _, establishment = data
    if establishment.status != "APPROVED":
        raise EstablishmentAccessError(establishment.status)
    return data
