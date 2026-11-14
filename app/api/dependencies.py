from collections.abc import AsyncGenerator

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.session import session_factory
from app.models.establishment import Establishment
from app.models.user import User

bearer_scheme = HTTPBearer(auto_error=False)


class AccountSuspendedError(Exception):
    """Cuenta suspendida por un admin: 403 `{"detail", "code": "ACCOUNT_SUSPENDED", "reason"}`.

    Se lanza en `get_current_user` (así una cookie ya emitida deja de servir de inmediato), en el login
    y en el canje del código de Google. `POST /auth/logout` no la exige.
    """

    detail = "Tu cuenta está suspendida."
    code = "ACCOUNT_SUSPENDED"

    def __init__(self, reason: str | None) -> None:
        self.reason = reason
        super().__init__(self.detail)


def ensure_not_suspended(user: User) -> None:
    if user.status == "SUSPENDED":
        raise AccountSuspendedError(user.suspension_reason)


def ensure_consents(user: User) -> None:
    """403 `CONSENT_REQUIRED` si falta aceptar la versión vigente de la política o los términos (B8).

    Se exige en las dependencias `require_*`; `get_current_user` no la exige, para que la cuenta pueda
    ver su perfil, aceptar, descargar sus datos, eliminar la cuenta y cerrar sesión.
    """
    from app.services.privacy_service import ensure_consents as check

    check(user)


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
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError, jwt.InvalidTokenError) as error:
        raise unauthorized from error

    user = await session.scalar(select(User).where(User.id == user_id))
    # Una cuenta eliminada (lápida, B8) no tiene sesión válida aunque la cookie siga sin expirar.
    if user is None or user.status == "DELETED":
        raise unauthorized
    ensure_not_suspended(user)
    return user


async def get_optional_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> User | None:
    # Una cuenta suspendida navega las páginas públicas como un visitante.
    try:
        return await get_current_user(request, credentials, session)
    except (HTTPException, AccountSuspendedError):
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
    ensure_consents(current_user)
    return current_user


async def require_active_user(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.phone_verified or current_user.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Debes completar la verificación telefónica.",
        )
    ensure_consents(current_user)
    return current_user


async def require_reviewer(current_user: User = Depends(get_current_user)) -> User:
    """Cuenta que puede publicar reseñas: rol `user`, activa y con teléfono verificado.

    Las demás condiciones (local aprobado, no ser el dueño, una reseña por local) se comprueban
    en `review_service.check_can_review`.
    """
    from app.services.review_service import BLOCK_MESSAGES, account_block_reason

    reason = account_block_reason(current_user)
    if reason is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=BLOCK_MESSAGES[reason])
    ensure_consents(current_user)
    return current_user


async def require_planner(current_user: User = Depends(get_current_user)) -> User:
    """Cuenta que puede crear y ver planes: rol `user`, activa y con teléfono verificado (403 con `code`)."""
    from app.services.plan_service import check_planner

    check_planner(current_user)
    ensure_consents(current_user)
    return current_user


async def require_favorites_user(current_user: User = Depends(get_current_user)) -> User:
    """Cuenta que puede guardar favoritos: rol `user`, activa y con teléfono verificado (403 con `code`)."""
    from app.services.favorite_service import check_favorites_user

    check_favorites_user(current_user)
    ensure_consents(current_user)
    return current_user


class EstablishmentAccessError(Exception):
    """Acceso denegado al panel por el estado de aprobación; se responde 403 con el estado actual."""

    messages = {
        "PENDING": "Establecimiento en revisión",
        "REJECTED": "Establecimiento rechazado",
        "SUSPENDED": "Establecimiento suspendido",
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
    ensure_consents(current_user)
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


async def get_establishment_for_admin(
    establishment_id: int,
    admin: User = Depends(require_admin),
    session: AsyncSession = Depends(get_db),
) -> tuple[User, Establishment]:
    """Establecimiento indicado en la ruta (cualquier estado) para que el admin lo gestione."""
    establishment = await session.get(Establishment, establishment_id)
    if establishment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Establecimiento no encontrado")
    return admin, establishment
