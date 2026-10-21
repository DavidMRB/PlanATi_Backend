from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, require_approved_restaurant, require_restaurant_user
from app.models.establishment import Establishment, EstablishmentImage, MenuItem
from app.models.user import User
from app.schemas.establishment import EstablishmentImageResponse, EstablishmentResponse, MenuItemResponse
from app.schemas.restaurant import (
    ComboCreate,
    ComboUpdate,
    EstablishmentImageCreate,
    ProductCreate,
    ProductUpdate,
    RestaurantProfileUpdate,
    RestaurantReapplyResponse,
    RestaurantStatusResponse,
    UploadUrlResponse,
)
from app.services import restaurant_service
from app.services.restaurant_service import (
    CatalogConflictError,
    CatalogValidationError,
    EstablishmentTransitionError,
)
from app.services.storage import build_restaurant_upload_url

router = APIRouter(prefix="/restaurant", tags=["restaurant"])

RestaurantContext = tuple[User, Establishment]


# --- Estado y re-aplicación (accesibles en cualquier estado) ---------------------------------


@router.get("/status", response_model=RestaurantStatusResponse)
async def get_restaurant_status(
    context: RestaurantContext = Depends(require_restaurant_user),
) -> RestaurantStatusResponse:
    _, establishment = context
    return RestaurantStatusResponse(
        establishment_id=establishment.id,
        name=establishment.name,
        category=establishment.category,
        address=establishment.address,
        status=establishment.status,
        rejection_reason=establishment.rejection_reason,
    )


@router.patch("/reapply", response_model=RestaurantReapplyResponse)
async def reapply_restaurant(
    data: RestaurantProfileUpdate,
    context: RestaurantContext = Depends(require_restaurant_user),
    session: AsyncSession = Depends(get_db),
) -> RestaurantReapplyResponse:
    _, establishment = context
    try:
        establishment = await restaurant_service.reapply_establishment(
            session, establishment, data.model_dump(exclude_unset=True)
        )
    except EstablishmentTransitionError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return RestaurantReapplyResponse(
        establishment_id=establishment.id,
        status=establishment.status,
        message="Solicitud corregida y reenviada a revisión exitosamente.",
    )


@router.post("/upload-url", response_model=UploadUrlResponse)
async def create_restaurant_upload_url(
    folder: Literal["establishments", "menu", "products"] = Query(...),
    file_extension: str = Query(default=".jpg", max_length=6),
    _: RestaurantContext = Depends(require_restaurant_user),
) -> dict[str, str]:
    return build_restaurant_upload_url(folder, file_extension)


# --- Perfil (requiere aprobación) ------------------------------------------------------------


@router.get("/profile", response_model=EstablishmentResponse)
async def get_restaurant_profile(
    # Sin exigir aprobación: un restaurante pendiente o rechazado necesita sus datos para corregir la solicitud.
    context: RestaurantContext = Depends(require_restaurant_user),
) -> Establishment:
    return context[1]


IMAGE_PROFILE_FIELDS = {"profile_image_url", "banner_image_url"}


@router.patch("/profile", response_model=EstablishmentResponse)
async def update_restaurant_profile(
    data: RestaurantProfileUpdate,
    context: RestaurantContext = Depends(require_restaurant_user),
    session: AsyncSession = Depends(get_db),
) -> Establishment:
    changes = data.model_dump(exclude_unset=True)
    establishment = context[1]
    # Mientras la solicitud está en revisión solo se permiten las imágenes del alta; el resto requiere APPROVED.
    if establishment.status != "APPROVED" and not set(changes) <= IMAGE_PROFILE_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo puedes actualizar las imágenes mientras tu establecimiento está en revisión.",
        )
    return await restaurant_service.update_establishment_profile(session, establishment, changes)


# --- Imágenes: galería y menú físico ---------------------------------------------------------


@router.get("/images", response_model=list[EstablishmentImageResponse])
async def list_restaurant_images(
    image_type: Literal["GALLERY", "MENU"] | None = Query(default=None),
    context: RestaurantContext = Depends(require_approved_restaurant),
    session: AsyncSession = Depends(get_db),
) -> list[EstablishmentImage]:
    return await restaurant_service.list_establishment_images(session, context[1], image_type)


@router.post("/images", response_model=EstablishmentImageResponse, status_code=status.HTTP_201_CREATED)
async def create_restaurant_image(
    data: EstablishmentImageCreate,
    context: RestaurantContext = Depends(require_approved_restaurant),
    session: AsyncSession = Depends(get_db),
) -> EstablishmentImage:
    return await restaurant_service.add_establishment_image(session, context[1], data.model_dump())


@router.delete("/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_restaurant_image(
    image_id: int,
    context: RestaurantContext = Depends(require_approved_restaurant),
    session: AsyncSession = Depends(get_db),
) -> None:
    if not await restaurant_service.delete_establishment_image(session, context[1], image_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Imagen no encontrada")


# --- Catálogo: productos ---------------------------------------------------------------------


async def _get_item_or_404(
    session: AsyncSession, establishment: Establishment, item_id: int, *, is_combo: bool
) -> MenuItem:
    item = await restaurant_service.get_catalog_item(session, establishment, item_id, is_combo=is_combo)
    if item is None:
        detail = "Combo no encontrado" if is_combo else "Producto no encontrado"
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
    return item


@router.get("/products", response_model=list[MenuItemResponse])
async def list_restaurant_products(
    context: RestaurantContext = Depends(require_approved_restaurant),
    session: AsyncSession = Depends(get_db),
) -> list[MenuItem]:
    return await restaurant_service.list_catalog(session, context[1])


@router.post("/products", response_model=MenuItemResponse, status_code=status.HTTP_201_CREATED)
async def create_restaurant_product(
    data: ProductCreate,
    context: RestaurantContext = Depends(require_approved_restaurant),
    session: AsyncSession = Depends(get_db),
) -> MenuItem:
    return await restaurant_service.create_product(session, context[1], data.model_dump())


@router.patch("/products/{product_id}", response_model=MenuItemResponse)
async def update_restaurant_product(
    product_id: int,
    data: ProductUpdate,
    context: RestaurantContext = Depends(require_approved_restaurant),
    session: AsyncSession = Depends(get_db),
) -> MenuItem:
    establishment = context[1]
    product = await _get_item_or_404(session, establishment, product_id, is_combo=False)
    return await restaurant_service.update_catalog_item(
        session, establishment, product, data.model_dump(exclude_unset=True)
    )


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_restaurant_product(
    product_id: int,
    context: RestaurantContext = Depends(require_approved_restaurant),
    session: AsyncSession = Depends(get_db),
) -> None:
    product = await _get_item_or_404(session, context[1], product_id, is_combo=False)
    try:
        await restaurant_service.delete_product(session, product)
    except CatalogConflictError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


# --- Catálogo: combos ------------------------------------------------------------------------


@router.post("/combos", response_model=MenuItemResponse, status_code=status.HTTP_201_CREATED)
async def create_restaurant_combo(
    data: ComboCreate,
    context: RestaurantContext = Depends(require_approved_restaurant),
    session: AsyncSession = Depends(get_db),
) -> MenuItem:
    try:
        return await restaurant_service.create_combo(session, context[1], data.model_dump())
    except CatalogValidationError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.patch("/combos/{combo_id}", response_model=MenuItemResponse)
async def update_restaurant_combo(
    combo_id: int,
    data: ComboUpdate,
    context: RestaurantContext = Depends(require_approved_restaurant),
    session: AsyncSession = Depends(get_db),
) -> MenuItem:
    establishment = context[1]
    combo = await _get_item_or_404(session, establishment, combo_id, is_combo=True)
    # exclude_unset también omitiría el quantity por defecto de cada ítem; se serializan completos.
    changes = data.model_dump(exclude_unset=True, exclude={"items"})
    if data.items is not None:
        changes["items"] = [item.model_dump() for item in data.items]
    try:
        return await restaurant_service.update_combo(session, establishment, combo, changes)
    except CatalogValidationError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.delete("/combos/{combo_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_restaurant_combo(
    combo_id: int,
    context: RestaurantContext = Depends(require_approved_restaurant),
    session: AsyncSession = Depends(get_db),
) -> None:
    combo = await _get_item_or_404(session, context[1], combo_id, is_combo=True)
    await restaurant_service.delete_combo(session, combo)
