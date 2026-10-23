from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_optional_current_user, require_active_user
from app.models.establishment import Establishment
from app.models.user import User
from app.schemas.establishment import (
    EstablishmentCreate,
    EstablishmentDetailResponse,
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


@router.get("/{establishment_id}", response_model=EstablishmentDetailResponse)
async def get_establishment_detail(
    establishment_id: int,
    viewer: User | None = Depends(get_optional_current_user),
    session: AsyncSession = Depends(get_db),
) -> EstablishmentDetailResponse:
    establishment = await get_establishment(session, establishment_id)
    can_preview = viewer is not None and (
        viewer.role == "admin" or (establishment is not None and establishment.owner_id == viewer.id)
    )
    if establishment is None or (establishment.status != "APPROVED" and not can_preview):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Establecimiento no encontrado")

    available_items = [item for item in establishment.menu_items if item.is_available]
    ratings = [review.rating for review in establishment.reviews]
    base = EstablishmentResponse.model_validate(establishment, from_attributes=True)
    return EstablishmentDetailResponse(
        **base.model_dump(),
        products=[item for item in available_items if not item.is_combo],
        combos=[item for item in available_items if item.is_combo],
        gallery_images=[image for image in establishment.images if image.image_type == "GALLERY"],
        menu_images=[image for image in establishment.images if image.image_type == "MENU"],
        reviews_count=len(ratings),
        average_rating=round(sum(ratings) / len(ratings), 2) if ratings else None,
    )


def _reject_restaurant_accounts(current_user: User) -> None:
    # Las cuentas de restaurante gestionan su establecimiento desde /restaurant, sujeto a aprobación.
    if current_user.role == "restaurant":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Las cuentas de restaurante gestionan su establecimiento desde /restaurant.",
        )


@router.post("", response_model=EstablishmentResponse, status_code=status.HTTP_201_CREATED)
async def create_establishment_endpoint(
    data: EstablishmentCreate,
    current_user: User = Depends(require_active_user),
    session: AsyncSession = Depends(get_db),
) -> Establishment:
    _reject_restaurant_accounts(current_user)
    return await create_establishment(session, current_user.id, data)


@router.patch("/{establishment_id}", response_model=EstablishmentResponse)
async def update_establishment_endpoint(
    establishment_id: int,
    data: EstablishmentUpdate,
    current_user: User = Depends(require_active_user),
    session: AsyncSession = Depends(get_db),
) -> Establishment:
    _reject_restaurant_accounts(current_user)
    establishment = await get_establishment(session, establishment_id)
    if establishment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Establecimiento no encontrado")
    if establishment.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para editarlo")
    return await update_establishment(session, establishment, data)
