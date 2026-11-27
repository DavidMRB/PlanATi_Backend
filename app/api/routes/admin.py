"""Consola de administración: dashboard y establecimientos (aprobar, rechazar, suspender, editar como
el establecimiento). Usuarios en `admin_users.py`; reseñas, reportes y bitácora en `admin_moderation.py`."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.api.dependencies import get_db, get_establishment_for_admin, require_admin
from app.api.routes.catalog_router import build_catalog_router
from app.models.establishment import Establishment
from app.models.user import User
from app.schemas.admin import (
    AdminDashboardResponse,
    AdminEstablishmentDetail,
    AdminEstablishmentListItem,
    AdminEstablishmentUpdate,
    EstablishmentDecisionResponse,
    EstablishmentRejectRequest,
    ReactivateRequest,
    SuspendRequest,
)
from app.schemas.establishment import EstablishmentResponse
from app.schemas.restaurant import UploadUrlResponse
from app.services import admin_service, moderation_service
from app.services.excel_service import XLSX_RESPONSE, establishments_workbook, export_menu, export_reviews
from app.services.establishment_service import OutOfServiceAreaError
from app.services.restaurant_service import (
    EstablishmentTransitionError,
    approve_establishment,
    get_establishment_with_owner,
    list_establishments_for_admin,
    reject_establishment,
)
from app.services.storage import build_restaurant_upload_url

# GUIA #10 TEMA: Subalgoritmos (funciones, procedimientos y modularización) -> modularización: cada opción del panel de administración es una función-ruta
# (no hay un menú `while True` con `input()`). `Depends(get_db)` inyecta la sesión de base de datos
# como parámetro en lugar de usar variables globales.
router = APIRouter(prefix="/admin", tags=["admin"])
AdminEstablishment = tuple[User, Establishment]


# Estadísticas del panel de administración (conteos de usuarios, establecimientos y moderación).
@router.get("/dashboard", response_model=AdminDashboardResponse)
async def admin_dashboard(
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> AdminDashboardResponse:
    counts = await admin_service.dashboard_counts(session)
    counts.update(await moderation_service.moderation_counts(session))
    return AdminDashboardResponse(**counts)


# --- Establecimientos -----------------------------------------------------------------------------


# GUIA #10 TEMA: Subalgoritmos (funciones, procedimientos y modularización) -> función auxiliar reutilizada por el listado y el detalle: convierte el par
# (establecimiento, dueño) en la respuesta del panel.
def _list_item(establishment: Establishment, owner: User, open_reports: int) -> AdminEstablishmentListItem:
    return AdminEstablishmentListItem(
        id=establishment.id,
        name=establishment.name,
        category=establishment.category,
        address=establishment.address,
        owner_id=owner.id,
        owner_email=owner.email,
        manager_name=establishment.manager_name,
        phone=establishment.phone,
        contact_email=establishment.contact_email,
        status=establishment.status,
        created_at=establishment.created_at,
        establishment_type=establishment.establishment_type,
        city=establishment.city,
        rating_avg=establishment.rating_avg,
        rating_count=establishment.rating_count,
        has_location=establishment.latitude is not None and establishment.longitude is not None,
        open_reports_count=open_reports,
        suspension_reason=establishment.suspension_reason,
    )


# GUIA #10 TEMA: Subalgoritmos (funciones, procedimientos y modularización) -> función que devuelve una tupla (establecimiento, dueño) o lanza un 404.
# GUIA #8 TEMA: Vectores (ordenamiento y búsqueda) -> búsqueda por id con llave primaria.
async def _get_establishment_or_404(session: AsyncSession, establishment_id: int) -> tuple[Establishment, User]:
    row = await get_establishment_with_owner(session, establishment_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Establecimiento no encontrado")
    return row


# Listado de solicitudes y establecimientos para el administrador (filtro por estado y búsqueda).
@router.get("/establishments", response_model=list[AdminEstablishmentListItem])
async def list_establishments_admin(
    status_filter: Literal["PENDING", "APPROVED", "REJECTED", "SUSPENDED", "ALL"] = Query(
        default="ALL", alias="status"
    ),
    search: str | None = Query(default=None, max_length=150),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[AdminEstablishmentListItem]:
    rows = await list_establishments_for_admin(session, status_filter, search, skip, limit)
    # GUIA #6 TEMA: Ciclos -> comprensión de lista que recorre las filas;
    # GUIA #7 TEMA: Cadenas, listas, tuplas y diccionarios -> cada fila es una tupla que se desempaqueta en (establecimiento, dueño, reportes).
    return [_list_item(establishment, owner, reports) for establishment, owner, reports in rows]


@router.get("/exports/establishments.xlsx", response_class=Response, responses=XLSX_RESPONSE)
async def export_admin_establishments(
    status_filter: Literal["PENDING", "APPROVED", "REJECTED", "SUSPENDED", "ALL"] = Query(
        default="ALL", alias="status"
    ),
    search: str | None = Query(default=None, max_length=150),
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> Response:
    rows = await list_establishments_for_admin(session, status_filter, search, skip=0, limit=None)
    return await run_in_threadpool(establishments_workbook, rows)


@router.get("/establishments/{establishment_id}/exports/menu.xlsx", response_class=Response, responses=XLSX_RESPONSE)
async def export_admin_establishment_menu(
    context: AdminEstablishment = Depends(get_establishment_for_admin),
    session: AsyncSession = Depends(get_db),
) -> Response:
    return await export_menu(session, context[1])


@router.get("/establishments/{establishment_id}/exports/reviews.xlsx", response_class=Response, responses=XLSX_RESPONSE)
async def export_admin_establishment_reviews(
    context: AdminEstablishment = Depends(get_establishment_for_admin),
    session: AsyncSession = Depends(get_db),
) -> Response:
    return await export_reviews(session, context[1])


@router.get("/establishments/{establishment_id}", response_model=AdminEstablishmentDetail)
async def get_establishment_admin(
    establishment_id: int,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> AdminEstablishmentDetail:
    establishment, owner = await _get_establishment_or_404(session, establishment_id)
    reports = await session.scalar(
        select(admin_service.establishment_open_reports_expr()).where(Establishment.id == establishment.id)
    )
    return AdminEstablishmentDetail(
        **_list_item(establishment, owner, int(reports or 0)).model_dump(),
        description=establishment.description,
        rejection_reason=establishment.rejection_reason,
        profile_image_url=establishment.profile_image_url,
        banner_image_url=establishment.banner_image_url,
        owner_full_name=owner.full_name,
        owner_status=owner.status,
        images=establishment.images,
        latitude=establishment.latitude,
        longitude=establishment.longitude,
        location_source=establishment.location_source,
        google_place_id=establishment.google_place_id,
        price_range=establishment.price_range,
        ranking_score=establishment.ranking_score,
    )


# Aprobación de un restaurante: PENDING -> APPROVED (409 si el estado actual no lo permite).
@router.post("/establishments/{establishment_id}/approve", response_model=EstablishmentDecisionResponse)
async def approve_establishment_admin(
    establishment_id: int,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> EstablishmentDecisionResponse:
    establishment, _owner = await _get_establishment_or_404(session, establishment_id)
    try:
        establishment = await approve_establishment(session, establishment)
    except EstablishmentTransitionError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    # GUIA #7 TEMA: Cadenas, listas, tuplas y diccionarios -> lista de avisos que se llena con `append()` y viaja en la respuesta JSON.
    warnings = []
    if establishment.latitude is None or establishment.longitude is None:
        warnings.append("El establecimiento no tiene ubicación y no aparecerá en el mapa.")
    return EstablishmentDecisionResponse(
        id=establishment.id,
        status="APPROVED",
        message="Establecimiento aprobado exitosamente.",
        warnings=warnings,
    )


# Rechazo de una solicitud: PENDING -> REJECTED con el motivo.
@router.post("/establishments/{establishment_id}/reject", response_model=EstablishmentDecisionResponse)
async def reject_establishment_admin(
    establishment_id: int,
    data: EstablishmentRejectRequest,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> EstablishmentDecisionResponse:
    """Rechaza una solicitud PENDING (409 en otro estado; un local aprobado se suspende)."""
    establishment, _owner = await _get_establishment_or_404(session, establishment_id)
    try:
        establishment = await reject_establishment(session, establishment, data.reason)
    except EstablishmentTransitionError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return EstablishmentDecisionResponse(
        id=establishment.id,
        status="REJECTED",
        rejection_reason=establishment.rejection_reason,
        message="Establecimiento rechazado.",
    )


# Suspensión de un local aprobado (sale del directorio público).
@router.post("/establishments/{establishment_id}/suspend", response_model=EstablishmentDecisionResponse)
async def suspend_establishment_admin(
    data: SuspendRequest,
    context: AdminEstablishment = Depends(get_establishment_for_admin),
    session: AsyncSession = Depends(get_db),
) -> EstablishmentDecisionResponse:
    """APPROVED → SUSPENDED: sale del directorio, del mapa y de las reseñas públicas. Notifica al dueño."""
    admin, establishment = context
    await admin_service.suspend_establishment(session, admin, establishment, data.reason)
    await session.commit()
    return EstablishmentDecisionResponse(
        id=establishment.id,
        status="SUSPENDED",
        suspension_reason=establishment.suspension_reason,
        message="Establecimiento suspendido.",
    )


@router.post("/establishments/{establishment_id}/reactivate", response_model=EstablishmentDecisionResponse)
async def reactivate_establishment_admin(
    data: ReactivateRequest | None = None,
    context: AdminEstablishment = Depends(get_establishment_for_admin),
    session: AsyncSession = Depends(get_db),
) -> EstablishmentDecisionResponse:
    """SUSPENDED → APPROVED. Notifica al dueño."""
    admin, establishment = context
    await admin_service.reactivate_establishment(session, admin, establishment, data.note if data else None)
    await session.commit()
    return EstablishmentDecisionResponse(
        id=establishment.id, status="APPROVED", message="Establecimiento reactivado."
    )


# Edición del perfil por el administrador.
# GUIA #7 TEMA: Cadenas, listas, tuplas y diccionarios -> `model_dump(exclude_unset=True)` deja en un diccionario solo los campos enviados.
@router.patch("/establishments/{establishment_id}", response_model=EstablishmentResponse)
async def update_establishment_admin(
    data: AdminEstablishmentUpdate,
    context: AdminEstablishment = Depends(get_establishment_for_admin),
    session: AsyncSession = Depends(get_db),
) -> Establishment:
    """Editar el perfil como el establecimiento (en cualquier estado). Queda en la bitácora con los
    valores antes/después y el dueño recibe un aviso."""
    admin, establishment = context
    changes = data.model_dump(exclude_unset=True, exclude={"reason"})
    try:
        await admin_service.update_establishment_as_admin(session, admin, establishment, changes, data.reason)
    except OutOfServiceAreaError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    await session.commit()
    await session.refresh(establishment)
    return establishment


@router.post("/establishments/{establishment_id}/upload-url", response_model=UploadUrlResponse)
async def create_admin_upload_url(
    folder: Literal["establishments", "menu", "products"] = Query(...),
    file_extension: str = Query(default=".jpg", max_length=6),
    _: AdminEstablishment = Depends(get_establishment_for_admin),
) -> dict[str, str]:
    return build_restaurant_upload_url(folder, file_extension)


# Productos, combos, fotos y horarios del local indicado, como en /restaurant/* (con bitácora y aviso).
router.include_router(
    build_catalog_router(get_establishment_for_admin, audit=True),
    prefix="/establishments/{establishment_id}",
)
