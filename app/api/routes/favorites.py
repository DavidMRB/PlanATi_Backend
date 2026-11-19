"""Favoritos del usuario ("Mis Favoritos")."""

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, require_favorites_user
from app.models.user import User
from app.schemas.common import Page
from app.schemas.establishment import EstablishmentListItem
from app.schemas.favorite import FavoriteIdsResponse
from app.services import favorite_service

router = APIRouter(prefix="/favorites", tags=["favorites"])


@router.get("", response_model=Page[EstablishmentListItem])
async def list_favorites(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=50),
    user: User = Depends(require_favorites_user),
    session: AsyncSession = Depends(get_db),
) -> Page[EstablishmentListItem]:
    """Favoritos aprobados, el guardado más recientemente primero (los no aprobados no salen)."""
    items, total = await favorite_service.list_favorites(session, user.id, skip=skip, limit=limit)
    return Page[EstablishmentListItem](
        items=[EstablishmentListItem.model_validate(e, from_attributes=True) for e in items],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/ids", response_model=FavoriteIdsResponse)
async def list_favorite_ids(
    user: User = Depends(require_favorites_user),
    session: AsyncSession = Depends(get_db),
) -> FavoriteIdsResponse:
    """Solo los ids, para marcar el corazón en las tarjetas del directorio, el mapa o cercanos."""
    return FavoriteIdsResponse(establishment_ids=await favorite_service.favorite_ids(session, user.id))


@router.put("/{establishment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def add_favorite(
    establishment_id: int,
    user: User = Depends(require_favorites_user),
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Idempotente. 404 si el establecimiento no existe o no está aprobado."""
    await favorite_service.add_favorite(session, user, establishment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/{establishment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_favorite(
    establishment_id: int,
    user: User = Depends(require_favorites_user),
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Idempotente: 204 aunque no fuera favorito."""
    await favorite_service.remove_favorite(session, user, establishment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
