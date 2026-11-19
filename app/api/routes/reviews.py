from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db, require_active_user, require_reviewer
from app.models.establishment import Establishment
from app.models.review import ReviewImage, ReviewReply
from app.models.user import User
from app.schemas.common import Page
from app.schemas.restaurant import UploadUrlResponse
from app.schemas.review import (
    MyReview,
    ReviewCreate,
    ReviewImageCreate,
    ReviewImageResponse,
    ReviewPublic,
    ReviewReplyCreate,
    ReviewReplyResponse,
    ReviewSort,
    ReviewUpdate,
)
from app.services import review_service
from app.services.review_service import establishment_summary, to_my_review, to_public_review
from app.services.storage import build_review_upload_url

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.post("/upload-url", response_model=UploadUrlResponse)
async def generate_upload_url(
    file_extension: str = Query(default=".jpg", max_length=10),
    _: User = Depends(require_reviewer),
) -> dict[str, str]:
    """URL prefirmada en la carpeta `reviews/` de R2 para subir una imagen antes de publicar la reseña."""
    return build_review_upload_url(file_extension)


@router.get("/establishments/{establishment_id}", response_model=Page[ReviewPublic])
async def get_reviews_for_establishment(
    establishment_id: int,
    sort: ReviewSort = Query(default="recent"),
    rating: int | None = Query(default=None, ge=1, le=5, description="Solo reseñas con esas estrellas."),
    with_photos: bool = Query(default=False),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=50),
    session: AsyncSession = Depends(get_db),
) -> Page[ReviewPublic]:
    """Reseñas visibles de un establecimiento aprobado, paginadas."""
    reviews, total = await review_service.list_reviews_for_establishment(
        session, establishment_id, sort=sort, rating=rating, with_photos=with_photos, skip=skip, limit=limit
    )
    return Page[ReviewPublic](items=[to_public_review(r) for r in reviews], total=total, skip=skip, limit=limit)


@router.post(
    "/establishments/{establishment_id}", response_model=ReviewPublic, status_code=status.HTTP_201_CREATED
)
async def create_review_endpoint(
    establishment_id: int,
    request: ReviewCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ReviewPublic:
    """Publica la reseña del usuario (una por establecimiento). 409 con `review_id` si ya existe."""
    review = await review_service.create_review(
        session,
        current_user,
        establishment_id,
        rating=request.rating,
        comment=request.comment,
        image_urls=request.image_urls,
    )
    return to_public_review(review)


@router.get("/me", response_model=Page[MyReview])
async def list_my_reviews(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> Page[MyReview]:
    """Todas mis reseñas, incluidas las ocultas o bloqueadas por moderación (con su motivo)."""
    items, total = await review_service.list_my_reviews(session, current_user, skip=skip, limit=limit)
    return Page[MyReview](items=items, total=total, skip=skip, limit=limit)


@router.patch("/{review_id}", response_model=MyReview)
async def update_review_endpoint(
    review_id: int,
    request: ReviewUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> MyReview:
    """Edita mi reseña. Si su comentario está bloqueado, el texto nuevo queda pendiente de revisión
    (`flagged_for_review=true`) y sigue sin publicarse."""
    review = await review_service.update_review(
        session, current_user, review_id, request.model_dump(exclude_unset=True)
    )
    establishment = await session.get(Establishment, review.establishment_id)
    assert establishment is not None
    return to_my_review(review, establishment_summary(establishment))


@router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review_endpoint(
    review_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> Response:
    await review_service.delete_review(session, current_user, review_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Rutas legadas ----------------------------------------------------------------------------


@router.post(
    "/{review_id}/images",
    response_model=ReviewImageResponse,
    status_code=status.HTTP_201_CREATED,
    deprecated=True,
)
async def create_review_image_endpoint(
    review_id: int,
    request: ReviewImageCreate,
    current_user: User = Depends(require_active_user),
    session: AsyncSession = Depends(get_db),
) -> ReviewImage:
    """Obsoleta: envía `image_urls` al crear o editar la reseña."""
    return await review_service.add_review_image(session, current_user, review_id, request.image_url)


@router.post("/{review_id}/upload-url", response_model=UploadUrlResponse, deprecated=True)
async def generate_review_upload_url(
    review_id: int,
    file_extension: str = Query(default=".jpg", max_length=10),
    current_user: User = Depends(require_reviewer),
    session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Obsoleta: usa POST /reviews/upload-url (no exige crear la reseña antes)."""
    await review_service.get_own_review(session, current_user, review_id)
    return build_review_upload_url(file_extension)


@router.post("/{review_id}/reply", response_model=ReviewReplyResponse, deprecated=True)
async def create_review_reply(
    review_id: int,
    request: ReviewReplyCreate,
    current_user: User = Depends(require_active_user),
    session: AsyncSession = Depends(get_db),
) -> ReviewReply:
    """Obsoleta: usa PUT /restaurant/reviews/{review_id}/reply.

    Crea o actualiza la respuesta (responder dos veces ya no da 500).
    """
    review = await session.get(review_service.Review, review_id)
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reseña no encontrada")
    establishment = await session.get(Establishment, review.establishment_id)
    if establishment is None or establishment.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para responder")
    updated, _ = await review_service.upsert_reply(session, establishment, review.id, request.comment)
    return updated.reply
