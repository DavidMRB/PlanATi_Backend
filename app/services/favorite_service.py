"""Favoritos: establecimientos guardados por los usuarios (rol `user`, activos y verificados).

Solo se pueden marcar locales `APPROVED`. Si un favorito deja de estar aprobado (suspendido, por
ejemplo), la fila se conserva pero no se lista; vuelve a aparecer si el local se reactiva.
"""

from typing import Any

from sqlalchemy import Select, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.establishment import Establishment
from app.models.favorite import Favorite
from app.models.user import User
from app.services.establishment_service import _LIST_LOAD_OPTIONS


class FavoriteError(Exception):
    status_code = 400

    def __init__(self, detail: str, **extra: Any) -> None:
        self.detail = detail
        self.extra = extra
        super().__init__(detail)


class FavoriteForbiddenError(FavoriteError):
    status_code = 403


class FavoriteNotFoundError(FavoriteError):
    status_code = 404


def check_favorites_user(user: User) -> None:
    if user.role != "user":
        raise FavoriteForbiddenError("Solo las cuentas de usuario pueden guardar favoritos.", code="ROLE_NOT_ALLOWED")
    if not user.phone_verified or user.status != "ACTIVE":
        raise FavoriteForbiddenError(
            "Debes completar la verificación telefónica para guardar favoritos.", code="PHONE_NOT_VERIFIED"
        )


def _approved_favorites(user_id: int) -> Select:
    return (
        select(Establishment)
        .join(Favorite, Favorite.establishment_id == Establishment.id)
        .where(Favorite.user_id == user_id, Establishment.status == "APPROVED")
    )


async def list_favorites(
    session: AsyncSession, user_id: int, *, skip: int = 0, limit: int = 20
) -> tuple[list[Establishment], int]:
    """Favoritos aprobados del usuario, el guardado más recientemente primero."""
    total = await session.scalar(select(func.count()).select_from(_approved_favorites(user_id).subquery()))
    query = (
        _approved_favorites(user_id)
        .options(*_LIST_LOAD_OPTIONS)
        .order_by(Favorite.created_at.desc(), Favorite.id.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await session.scalars(query)
    return list(result.all()), int(total or 0)


async def favorite_ids(session: AsyncSession, user_id: int) -> list[int]:
    """Ids de los favoritos aprobados (para marcar el corazón en las tarjetas del listado)."""
    query = (
        select(Favorite.establishment_id)
        .join(Establishment, Favorite.establishment_id == Establishment.id)
        .where(Favorite.user_id == user_id, Establishment.status == "APPROVED")
        .order_by(Favorite.created_at.desc(), Favorite.id.desc())
    )
    return list((await session.scalars(query)).all())


async def is_favorite(session: AsyncSession, user: User | None, establishment_id: int) -> bool:
    if user is None:
        return False
    found = await session.scalar(
        select(Favorite.id).where(Favorite.user_id == user.id, Favorite.establishment_id == establishment_id)
    )
    return found is not None


async def add_favorite(session: AsyncSession, user: User, establishment_id: int) -> None:
    """Idempotente: si ya era favorito no cambia nada (ni la fecha). Hace commit."""
    establishment = await session.get(Establishment, establishment_id)
    if establishment is None or establishment.status != "APPROVED":
        raise FavoriteNotFoundError("Establecimiento no encontrado")
    if await is_favorite(session, user, establishment_id):
        return
    session.add(Favorite(user_id=user.id, establishment_id=establishment_id))
    try:
        await session.commit()
    except IntegrityError:
        # Dos peticiones simultáneas: la otra ya lo guardó.
        await session.rollback()


async def remove_favorite(session: AsyncSession, user: User, establishment_id: int) -> None:
    """Idempotente: no falla si no era favorito ni si el local ya no existe o no está aprobado. Hace commit."""
    await session.execute(
        delete(Favorite).where(Favorite.user_id == user.id, Favorite.establishment_id == establishment_id)
    )
    await session.commit()
