from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.models.establishment import Establishment
from app.models.user import User
from app.schemas.establishment import (
    EstablishmentCreate,
    EstablishmentNearbyResponse,
    EstablishmentResponse,
    EstablishmentUpdate,
)
from app.services.establishment_service import (
    create_establishment,
    get_establishment,
    list_establishments,
    list_nearby_establishments,
    update_establishment,
)

router = APIRouter(prefix="/establishments", tags=["establishments"])


@router.get("", response_model=list[EstablishmentResponse])
async def search_establishments(
    search: str | None = Query(default=None),
    category: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db),
) -> list[Establishment]:
    return await list_establishments(session, search=search, category=category)


@router.get("/nearby", response_model=list[EstablishmentNearbyResponse])
async def get_nearby_establishments(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(default=5.0, gt=0),
    limit: int = Query(default=20, ge=1, le=50),
    session: AsyncSession = Depends(get_db),
) -> list[EstablishmentNearbyResponse]:
    nearby = await list_nearby_establishments(session, latitude, longitude, radius_km, limit)
    responses: list[EstablishmentNearbyResponse] = []
    for establishment, distance in nearby:
        base = EstablishmentResponse.model_validate(establishment, from_attributes=True)
        responses.append(EstablishmentNearbyResponse(**base.model_dump(), distance_km=round(distance, 2)))
    return responses


@router.get("/{establishment_id}", response_model=EstablishmentResponse)
async def get_establishment_detail(
    establishment_id: int,
    session: AsyncSession = Depends(get_db),
) -> Establishment:
    establishment = await get_establishment(session, establishment_id)
    if establishment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Establecimiento no encontrado")
    return establishment


@router.post("", response_model=EstablishmentResponse, status_code=status.HTTP_201_CREATED)
async def create_establishment_endpoint(
    data: EstablishmentCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> Establishment:
    return await create_establishment(session, current_user.id, data)


@router.patch("/{establishment_id}", response_model=EstablishmentResponse)
async def update_establishment_endpoint(
    establishment_id: int,
    data: EstablishmentUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> Establishment:
    establishment = await get_establishment(session, establishment_id)
    if establishment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Establecimiento no encontrado")
    if establishment.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para editarlo")
    return await update_establishment(session, establishment, data)
