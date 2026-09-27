from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.establishment import Establishment
from app.models.review import Review, ReviewImage, ReviewReply


async def get_establishment_by_id(session: AsyncSession, establishment_id: int) -> Establishment | None:
    return await session.get(Establishment, establishment_id)


async def list_reviews_for_establishment(session: AsyncSession, establishment_id: int) -> list[Review]:
    result = await session.scalars(
        select(Review)
        .where(Review.establishment_id == establishment_id)
        .options(selectinload(Review.images), selectinload(Review.reply))
        .order_by(Review.created_at.desc())
    )
    return list(result.all())


async def create_review(
    session: AsyncSession,
    user_id: int,
    establishment_id: int,
    rating: int,
    comment: str,
    image_urls: list[str],
) -> Review:
    review = Review(
        user_id=user_id,
        establishment_id=establishment_id,
        rating=rating,
        comment=comment.strip(),
    )
    session.add(review)
    await session.flush()

    for image_url in image_urls:
        session.add(ReviewImage(review_id=review.id, image_url=image_url.strip()))

    await session.commit()
    await session.refresh(review)
    return review


async def create_review_image(
    session: AsyncSession,
    review_id: int,
    image_url: str,
) -> ReviewImage:
    review_image = ReviewImage(review_id=review_id, image_url=image_url.strip())
    session.add(review_image)
    await session.commit()
    await session.refresh(review_image)
    return review_image


async def create_reply(
    session: AsyncSession,
    establishment_id: int,
    review_id: int,
    comment: str,
) -> ReviewReply:
    reply = ReviewReply(
        review_id=review_id,
        establishment_id=establishment_id,
        comment=comment.strip(),
    )
    session.add(reply)
    await session.commit()
    await session.refresh(reply)
    return reply
