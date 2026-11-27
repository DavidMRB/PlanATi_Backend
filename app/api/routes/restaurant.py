from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    EstablishmentAccessError,
    get_db,
    require_approved_restaurant,
    require_restaurant_user,
)
from app.api.routes.catalog_router import build_catalog_router
from app.models.establishment import Establishment
from app.models.user import User
from app.schemas.common import Page
from app.schemas.establishment import EstablishmentResponse
from app.schemas.restaurant import (
    RestaurantProfileUpdate,
    RestaurantReapplyResponse,
    RestaurantStatusResponse,
    UploadUrlResponse,
)
from app.schemas.review import ReviewPublic, ReviewReplyCreate, RestaurantReviewSummary
from app.services import restaurant_service, review_service
from app.services.excel_service import XLSX_RESPONSE, export_menu, export_reviews
from app.services.rating_service import category_rank, rating_distribution
from app.services.review_service import ReplyFilter, to_public_review
from app.services.establishment_service import OutOfServiceAreaError
from app.services.restaurant_service import EstablishmentTransitionError
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
        suspension_reason=establishment.suspension_reason,
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
    except OutOfServiceAreaError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
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
    if establishment.status == "SUSPENDED":
        raise EstablishmentAccessError(establishment.status)
    # Mientras la solicitud está en revisión solo se permiten las imágenes del alta; el resto requiere APPROVED.
    if establishment.status != "APPROVED" and not set(changes) <= IMAGE_PROFILE_FIELDS:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo puedes actualizar las imágenes mientras tu establecimiento está en revisión.",
        )
    try:
        return await restaurant_service.update_establishment_profile(session, establishment, changes)
    except OutOfServiceAreaError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


# --- Reseñas y respuestas (fase 2, B4) ---------------------------------------------------------


# GUIA 11 TEMA: Exportar menú -> el restaurante aprobado descarga únicamente su propio catálogo.
@router.get("/exports/menu.xlsx", response_class=Response, responses=XLSX_RESPONSE)
async def export_restaurant_menu(
    context: RestaurantContext = Depends(require_approved_restaurant),
    session: AsyncSession = Depends(get_db),
) -> Response:
    return await export_menu(session, context[1])


# GUIA 11 TEMA: Exportar reseñas -> el contexto autorizado limita la descarga al propio establecimiento.
@router.get("/exports/reviews.xlsx", response_class=Response, responses=XLSX_RESPONSE)
async def export_restaurant_reviews(
    context: RestaurantContext = Depends(require_approved_restaurant),
    session: AsyncSession = Depends(get_db),
) -> Response:
    return await export_reviews(session, context[1])


@router.get("/reviews", response_model=Page[ReviewPublic])
async def list_restaurant_reviews(
    status_filter: ReplyFilter = Query(default="all", alias="status"),
    rating: int | None = Query(default=None, ge=1, le=5),
    sort: Literal["recent", "rating_asc"] = Query(default="recent"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=50),
    context: RestaurantContext = Depends(require_approved_restaurant),
    session: AsyncSession = Depends(get_db),
) -> Page[ReviewPublic]:
    """Reseñas visibles de mi establecimiento. Un comentario bloqueado llega como aviso, sin su texto."""
    reviews, total = await review_service.list_reviews_for_owner(
        session, context[1], reply_status=status_filter, rating=rating, sort=sort, skip=skip, limit=limit
    )
    return Page[ReviewPublic](items=[to_public_review(r) for r in reviews], total=total, skip=skip, limit=limit)


@router.get("/reviews/summary", response_model=RestaurantReviewSummary)
async def get_restaurant_review_summary(
    context: RestaurantContext = Depends(require_approved_restaurant),
    session: AsyncSession = Depends(get_db),
) -> RestaurantReviewSummary:
    establishment = context[1]
    unanswered, response_rate = await review_service.reply_stats(session, establishment.id)
    return RestaurantReviewSummary(
        rating_avg=establishment.rating_avg,
        rating_count=establishment.rating_count,
        ranking_score=establishment.ranking_score,
        category_rank=await category_rank(session, establishment),
        distribution=await rating_distribution(session, establishment.id),
        unanswered_count=unanswered,
        response_rate=response_rate,
    )


@router.put("/reviews/{review_id}/reply", response_model=ReviewPublic)
async def upsert_restaurant_review_reply(
    review_id: int,
    data: ReviewReplyCreate,
    context: RestaurantContext = Depends(require_approved_restaurant),
    session: AsyncSession = Depends(get_db),
) -> ReviewPublic:
    """Crea o actualiza la respuesta (idempotente). El autor recibe una notificación solo al crearla."""
    review, _ = await review_service.upsert_reply(session, context[1], review_id, data.comment)
    return to_public_review(review)


@router.delete("/reviews/{review_id}/reply", status_code=status.HTTP_204_NO_CONTENT)
async def delete_restaurant_review_reply(
    review_id: int,
    context: RestaurantContext = Depends(require_approved_restaurant),
    session: AsyncSession = Depends(get_db),
) -> Response:
    await review_service.delete_reply(session, context[1], review_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Imágenes, productos, combos y horarios (compartidos con /admin/establishments/{id}) --------

router.include_router(build_catalog_router(require_approved_restaurant, audit=False))
