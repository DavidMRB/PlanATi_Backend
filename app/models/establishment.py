from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Text, Time, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Establishment(Base):
    __tablename__ = "establishments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str] = mapped_column(String(255), nullable=False)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    price_range: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    schedules: Mapped[list["Schedule"]] = relationship(
        back_populates="establishment", cascade="all, delete-orphan", lazy="selectin"
    )
    menu_items: Mapped[list["MenuItem"]] = relationship(
        back_populates="establishment", cascade="all, delete-orphan", lazy="selectin"
    )
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="establishment", cascade="all, delete-orphan", lazy="selectin"
    )


class Schedule(Base):
    __tablename__ = "schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    establishment_id: Mapped[int] = mapped_column(
        ForeignKey("establishments.id", ondelete="CASCADE"), nullable=False
    )
    day_of_week: Mapped[int] = mapped_column(Integer, nullable=False)
    opening_time: Mapped[time] = mapped_column(Time, nullable=False)
    closing_time: Mapped[time] = mapped_column(Time, nullable=False)

    establishment: Mapped[Establishment] = relationship(back_populates="schedules")


class MenuItem(Base):
    __tablename__ = "menu_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    establishment_id: Mapped[int] = mapped_column(
        ForeignKey("establishments.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    establishment: Mapped[Establishment] = relationship(back_populates="menu_items")
