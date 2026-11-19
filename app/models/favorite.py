from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Favorite(Base):
    """Establecimiento guardado por un usuario ("Mis Favoritos"). Uno por usuario+local."""

    __tablename__ = "favorites"
    __table_args__ = (
        UniqueConstraint("user_id", "establishment_id", name="uq_favorites_user_establishment"),
        Index("ix_favorites_user_created", "user_id", "created_at"),
        Index("ix_favorites_establishment_id", "establishment_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    establishment_id: Mapped[int] = mapped_column(
        ForeignKey("establishments.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
