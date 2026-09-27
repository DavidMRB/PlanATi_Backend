from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.models.review import Review, ReviewReply
from app.models.user import User
from app.schemas.review import (
    ReviewCreate,
    ReviewImageCreate,
    ReviewImageResponse,
    ReviewReplyCreate,
    ReviewReplyResponse,
    ReviewResponse,
)
from app.services.review_service import (
    create_reply,
    create_review,
    create_review_image,
    get_establishment_by_id,
    list_reviews_for_establishment,
)
from app.services.storage import build_review_upload_url

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.get("/establishments/{establishment_id}", response_model=list[ReviewResponse])
async def get_reviews_for_establishment(
    establishment_id: int,
    session: AsyncSession = Depends(get_db),
) -> list[Review]:
    establishment = await get_establishment_by_id(session, establishment_id)
    if establishment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Establecimiento no encontrado")
    return await list_reviews_for_establishment(session, establishment_id)


@router.post("/establishments/{establishment_id}", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
async def create_review_endpoint(
    establishment_id: int,
    request: ReviewCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> Review:
    establishment = await get_establishment_by_id(session, establishment_id)
    if establishment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Establecimiento no encontrado")

    return await create_review(
        session,
        user_id=current_user.id,
        establishment_id=establishment_id,
        rating=request.rating,
        comment=request.comment,
        image_urls=request.image_urls,
    )


@router.post("/{review_id}/images", response_model=ReviewImageResponse, status_code=status.HTTP_201_CREATED)
async def create_review_image_endpoint(
    review_id: int,
    request: ReviewImageCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ReviewReply:
    review = await session.get(Review, review_id)
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reseña no encontrada")
    if review.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el autor puede agregar imágenes")

    return await create_review_image(session, review.id, request.image_url)


@router.post("/{review_id}/upload-url")
async def generate_review_upload_url(
    review_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    review = await session.get(Review, review_id)
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reseña no encontrada")
    if review.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Solo el autor puede subir imágenes")

    return build_review_upload_url()


@router.post("/{review_id}/reply", response_model=ReviewReplyResponse)
async def create_review_reply(
    review_id: int,
    request: ReviewReplyCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ReviewReply:
    review = await session.get(Review, review_id)
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reseña no encontrada")

    establishment = await get_establishment_by_id(session, review.establishment_id)
    if establishment is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Establecimiento no encontrado")
    if establishment.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No tienes permisos para responder")

    return await create_reply(session, establishment.id, review.id, request.comment)
