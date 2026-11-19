from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, get_optional_current_user, require_active_user
from app.core.config import settings
from app.models.establishment import Establishment
from app.models.user import User
from app.schemas.establishment import (
    EstablishmentCreate,
    EstablishmentDetailResponse,
    EstablishmentListItem,
    EstablishmentNearbyItem,
    EstablishmentResponse,
    EstablishmentUpdate,
    MapMarker,
    MapMarkersResponse,
)
from app.schemas.geo import EstablishmentType
from app.services import favorite_service, review_service
from app.services.rating_service import category_rank, rating_distribution
from app.services.review_service import establishment_summary, to_my_review, to_public_review
from app.services.establishment_service import (
    DirectorySort,
    NearbySort,
    create_establishment,
    get_establishment,
    list_establishments,
    list_map_markers,
    list_nearby_establishments,
    update_establishment,
)

# Rutas públicas del directorio: listado, cercanos, mapa y detalle.
# GUIA #10 TEMA: Subalgoritmos (funciones, procedimientos y modularización) -> modularización: la ruta recibe y responde; la lógica vive en establishment_service.
router = APIRouter(prefix="/establishments", tags=["establishments"])

MIN_RATING_QUERY = Query(default=None, ge=1, le=5, description="Puntuación promedio mínima (1 a 5).")


# Directorio público con búsqueda, filtros y orden (`?sort=name` = orden alfabético ascendente).
@router.get("", response_model=list[EstablishmentListItem])
async def search_establishments(
    search: str | None = Query(default=None, max_length=150),
    category: str | None = Query(default=None, max_length=80),
    establishment_type: EstablishmentType | None = Query(default=None),
    min_rating: float | None = MIN_RATING_QUERY,
    sort: DirectorySort = Query(default="ranking"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=50),
    session: AsyncSession = Depends(get_db),
) -> list[Establishment]:
    """Directorio público (solo aprobados), sin reseñas; por defecto ordenado por ranking bayesiano."""
    return await list_establishments(
        session,
        search=search,
        category=category,
        establishment_type=establishment_type,
        min_rating=min_rating,
        sort=sort,
        skip=skip,
        limit=limit,
    )


# Establecimientos cercanos a la ubicación del usuario.
@router.get("/nearby", response_model=list[EstablishmentNearbyItem])
async def get_nearby_establishments(
    latitude: float = Query(..., ge=-90, le=90),
    longitude: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(default=5.0, gt=0, le=settings.nearby_max_radius_km),
    limit: int = Query(default=20, ge=1, le=50),
    category: str | None = Query(default=None, max_length=80),
    establishment_type: EstablishmentType | None = Query(default=None),
    min_rating: float | None = MIN_RATING_QUERY,
    sort: NearbySort = Query(default="distance"),
    session: AsyncSession = Depends(get_db),
) -> list[EstablishmentNearbyItem]:
    # La ubicación del usuario no se guarda ni se registra en logs (ver app/core/log_filters.py).
    nearby = await list_nearby_establishments(
        session,
        latitude,
        longitude,
        radius_km,
        limit,
        category=category,
        establishment_type=establishment_type,
        min_rating=min_rating,
        sort=sort,
    )
    # GUIA #6 TEMA: Ciclos -> `for` desempaqueta cada tupla (establecimiento, distancia) y arma la respuesta.
    responses: list[EstablishmentNearbyItem] = []
    for establishment, distance in nearby:
        base = EstablishmentListItem.model_validate(establishment, from_attributes=True)
        responses.append(EstablishmentNearbyItem(**base.model_dump(), distance_km=round(distance, 2)))
    return responses


@router.get("/map", response_model=MapMarkersResponse)
async def get_map_markers(
    north: float = Query(..., ge=-90, le=90),
    south: float = Query(..., ge=-90, le=90),
    east: float = Query(..., ge=-180, le=180),
    west: float = Query(..., ge=-180, le=180),
    category: str | None = Query(default=None, max_length=80),
    establishment_type: EstablishmentType | None = Query(default=None),
    min_rating: float | None = MIN_RATING_QUERY,
    limit: int = Query(default=min(300, settings.map_max_markers), ge=1, le=settings.map_max_markers),
    session: AsyncSession = Depends(get_db),
) -> MapMarkersResponse:
    """Marcadores del área visible del mapa, mejor posicionados primero."""
    if south >= north or west >= east:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El área del mapa no es válida: el sur debe ser menor que el norte y el oeste menor que el este.",
        )
    markers, truncated = await list_map_markers(
        session,
        south=south,
        west=west,
        north=north,
        east=east,
        limit=limit,
        category=category,
        establishment_type=establishment_type,
        min_rating=min_rating,
    )
    return MapMarkersResponse(items=[MapMarker(**marker) for marker in markers], truncated=truncated)


# Detalle de un establecimiento: 404 si no existe o no está aprobado (salvo vista previa del dueño o del admin).
# GUIA #8 TEMA: Vectores (ordenamiento y búsqueda) -> búsqueda por id con llave primaria indexada en lugar de un `for` secuencial.
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

    # GUIA #7 TEMA: Cadenas, listas, tuplas y diccionarios -> comprensiones de lista que separan productos, combos y fotos de galería y de menú.
    available_items = [item for item in establishment.menu_items if item.is_available]
    base = EstablishmentResponse.model_validate(establishment, from_attributes=True)

    viewer_review = None
    if viewer is not None:
        own = await review_service.find_user_review(session, viewer.id, establishment.id)
        if own is not None:
            viewer_review = to_my_review(own, establishment_summary(establishment))
    block = await review_service.check_can_review(session, viewer, establishment)
    if establishment.status != "APPROVED":
        block = block or "ROLE_NOT_ALLOWED"  # vista previa del dueño o del admin: nadie reseña aquí

    return EstablishmentDetailResponse(
        **base.model_dump(),
        products=[item for item in available_items if not item.is_combo],
        combos=[item for item in available_items if item.is_combo],
        gallery_images=[image for image in establishment.images if image.image_type == "GALLERY"],
        menu_images=[image for image in establishment.images if image.image_type == "MENU"],
        reviews_count=establishment.rating_count,
        average_rating=establishment.rating_avg,
        rating_distribution=await rating_distribution(session, establishment.id),
        category_rank=await category_rank(session, establishment),
        recent_reviews=[to_public_review(r) for r in await review_service.recent_reviews(session, establishment.id)],
        viewer_review=viewer_review,
        viewer_can_review=block is None,
        viewer_review_block=block,
        is_favorite=await favorite_service.is_favorite(session, viewer, establishment.id),
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
