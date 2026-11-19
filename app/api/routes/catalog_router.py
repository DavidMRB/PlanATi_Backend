"""Catálogo, fotos y horarios de un establecimiento, compartidos por dos paneles:

- `/restaurant/*` (el dueño, con `require_approved_restaurant`).
- `/admin/establishments/{establishment_id}/*` (un admin "como el establecimiento", con
  `get_establishment_for_admin` y `audit=True`: cada cambio deja `EDIT_CATALOG` en la bitácora y
  avisa al dueño, una vez por día).

La dependencia devuelve `(actor, establecimiento)`. La auditoría se agrega a la sesión ANTES de la
operación, que hace el único commit: si la operación falla (404/400/409) no queda nada registrado.
"""

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db
from app.models.establishment import Establishment, EstablishmentImage, MenuItem, Schedule
from app.models.user import User
from app.schemas.establishment import (
    EstablishmentImageResponse,
    MenuItemResponse,
    ScheduleInput,
    ScheduleResponse,
)
from app.schemas.restaurant import (
    ComboCreate,
    ComboUpdate,
    EstablishmentImageCreate,
    ProductCreate,
    ProductUpdate,
)
from app.services import admin_service, restaurant_service
from app.services.restaurant_service import CatalogConflictError, CatalogValidationError
from app.services.schedule_service import (
    MAX_SEGMENTS_PER_DAY,
    ScheduleValidationError,
    replace_schedules,
    sorted_schedules,
)

CatalogContext = tuple[User, Establishment]


def build_catalog_router(
    context_dependency: Callable[..., Awaitable[CatalogContext]], *, audit: bool
) -> APIRouter:
    router = APIRouter()

    async def log(session: AsyncSession, context: CatalogContext, operation: str, **details: Any) -> None:
        if audit:
            admin, establishment = context
            await admin_service.record_catalog_edit(session, admin, establishment, operation, details)

    async def get_item_or_404(
        session: AsyncSession, establishment: Establishment, item_id: int, *, is_combo: bool
    ) -> MenuItem:
        item = await restaurant_service.get_catalog_item(session, establishment, item_id, is_combo=is_combo)
        if item is None:
            detail = "Combo no encontrado" if is_combo else "Producto no encontrado"
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
        return item

    # --- Imágenes: galería y menú físico -----------------------------------------------------

    @router.get("/images", response_model=list[EstablishmentImageResponse])
    async def list_images(
        image_type: Literal["GALLERY", "MENU"] | None = Query(default=None),
        context: CatalogContext = Depends(context_dependency),
        session: AsyncSession = Depends(get_db),
    ) -> list[EstablishmentImage]:
        return await restaurant_service.list_establishment_images(session, context[1], image_type)

    @router.post("/images", response_model=EstablishmentImageResponse, status_code=status.HTTP_201_CREATED)
    async def create_image(
        data: EstablishmentImageCreate,
        context: CatalogContext = Depends(context_dependency),
        session: AsyncSession = Depends(get_db),
    ) -> EstablishmentImage:
        await log(session, context, "add_image", data=data.model_dump(mode="json"))
        return await restaurant_service.add_establishment_image(session, context[1], data.model_dump())

    @router.delete("/images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_image(
        image_id: int,
        context: CatalogContext = Depends(context_dependency),
        session: AsyncSession = Depends(get_db),
    ) -> None:
        await log(session, context, "delete_image", image_id=image_id)
        if not await restaurant_service.delete_establishment_image(session, context[1], image_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Imagen no encontrada")

    # --- Productos -----------------------------------------------------------------------------

    @router.get("/products", response_model=list[MenuItemResponse])
    async def list_products(
        context: CatalogContext = Depends(context_dependency),
        session: AsyncSession = Depends(get_db),
    ) -> list[MenuItem]:
        return await restaurant_service.list_catalog(session, context[1])

    @router.post("/products", response_model=MenuItemResponse, status_code=status.HTTP_201_CREATED)
    async def create_product(
        data: ProductCreate,
        context: CatalogContext = Depends(context_dependency),
        session: AsyncSession = Depends(get_db),
    ) -> MenuItem:
        await log(session, context, "create_product", data=data.model_dump(mode="json"))
        return await restaurant_service.create_product(session, context[1], data.model_dump())

    @router.patch("/products/{product_id}", response_model=MenuItemResponse)
    async def update_product(
        product_id: int,
        data: ProductUpdate,
        context: CatalogContext = Depends(context_dependency),
        session: AsyncSession = Depends(get_db),
    ) -> MenuItem:
        establishment = context[1]
        product = await get_item_or_404(session, establishment, product_id, is_combo=False)
        await log(
            session, context, "update_product", item_id=product_id, data=data.model_dump(mode="json", exclude_unset=True)
        )
        return await restaurant_service.update_catalog_item(
            session, establishment, product, data.model_dump(exclude_unset=True)
        )

    @router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_product(
        product_id: int,
        context: CatalogContext = Depends(context_dependency),
        session: AsyncSession = Depends(get_db),
    ) -> None:
        product = await get_item_or_404(session, context[1], product_id, is_combo=False)
        await log(session, context, "delete_product", item_id=product_id, name=product.name)
        try:
            await restaurant_service.delete_product(session, product)
        except CatalogConflictError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    # --- Combos --------------------------------------------------------------------------------

    @router.post("/combos", response_model=MenuItemResponse, status_code=status.HTTP_201_CREATED)
    async def create_combo(
        data: ComboCreate,
        context: CatalogContext = Depends(context_dependency),
        session: AsyncSession = Depends(get_db),
    ) -> MenuItem:
        await log(session, context, "create_combo", data=data.model_dump(mode="json"))
        try:
            return await restaurant_service.create_combo(session, context[1], data.model_dump())
        except CatalogValidationError as error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    @router.patch("/combos/{combo_id}", response_model=MenuItemResponse)
    async def update_combo(
        combo_id: int,
        data: ComboUpdate,
        context: CatalogContext = Depends(context_dependency),
        session: AsyncSession = Depends(get_db),
    ) -> MenuItem:
        establishment = context[1]
        combo = await get_item_or_404(session, establishment, combo_id, is_combo=True)
        # exclude_unset también omitiría el quantity por defecto de cada ítem; se serializan completos.
        changes = data.model_dump(exclude_unset=True, exclude={"items"})
        if data.items is not None:
            changes["items"] = [item.model_dump() for item in data.items]
        await log(session, context, "update_combo", item_id=combo_id, data=changes)
        try:
            return await restaurant_service.update_combo(session, establishment, combo, changes)
        except CatalogValidationError as error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    @router.delete("/combos/{combo_id}", status_code=status.HTTP_204_NO_CONTENT)
    async def delete_combo(
        combo_id: int,
        context: CatalogContext = Depends(context_dependency),
        session: AsyncSession = Depends(get_db),
    ) -> None:
        combo = await get_item_or_404(session, context[1], combo_id, is_combo=True)
        await log(session, context, "delete_combo", item_id=combo_id, name=combo.name)
        await restaurant_service.delete_combo(session, combo)

    # GUIA #9 TEMA: Matrices (creación, recorrido y operaciones) -> registro y consulta del horario semanal: GET devuelve los tramos ordenados
    # y PUT reemplaza la matriz completa (máximo 7 días x 3 tramos).
    # --- Horarios ------------------------------------------------------------------------------

    @router.get("/schedules", response_model=list[ScheduleResponse])
    async def get_schedules(context: CatalogContext = Depends(context_dependency)) -> list[Schedule]:
        """Horarios en hora de Colombia; 0 = lunes … 6 = domingo."""
        return sorted_schedules(context[1].schedules)

    @router.put("/schedules", response_model=list[ScheduleResponse])
    async def put_schedules(
        data: list[ScheduleInput] = Body(..., max_length=7 * MAX_SEGMENTS_PER_DAY),
        context: CatalogContext = Depends(context_dependency),
        session: AsyncSession = Depends(get_db),
    ) -> list[Schedule]:
        """Reemplaza todos los horarios. Si el cierre es menor que la apertura, el tramo cruza la
        medianoche. Máximo 3 tramos por día y sin solapes (400). Una lista vacía deja el local sin horarios."""
        await log(session, context, "replace_schedules", data=[item.model_dump(mode="json") for item in data])
        try:
            return await replace_schedules(session, context[1], data)
        except ScheduleValidationError as error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    return router
