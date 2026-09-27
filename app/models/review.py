from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    establishment_id: Mapped[int] = mapped_column(
        ForeignKey("establishments.id", ondelete="CASCADE"), nullable=False
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    images: Mapped[list["ReviewImage"]] = relationship(
        back_populates="review", cascade="all, delete-orphan", lazy="selectin"
    )
    reply: Mapped["ReviewReply | None"] = relationship(
        back_populates="review", cascade="all, delete-orphan", lazy="selectin", uselist=False
    )
    establishment: Mapped["Establishment"] = relationship(back_populates="reviews")


class ReviewImage(Base):
    __tablename__ = "review_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False)
    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    review: Mapped[Review] = relationship(back_populates="images")


class ReviewReply(Base):
    __tablename__ = "review_replies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[int] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    establishment_id: Mapped[int] = mapped_column(
        ForeignKey("establishments.id", ondelete="CASCADE"), nullable=False
    )
    comment: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    review: Mapped[Review] = relationship(back_populates="reply")
    establishment: Mapped["Establishment"] = relationship("Establishment")
