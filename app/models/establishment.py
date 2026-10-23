from datetime import datetime, time
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, Time, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.review import Review
    from app.models.user import User

ESTABLISHMENT_STATUSES = {"PENDING", "APPROVED", "REJECTED"}
IMAGE_TYPES = {"GALLERY", "MENU"}


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
    status: Mapped[str] = mapped_column(String(30), default="PENDING", index=True, nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Nullable en base de datos para conservar establecimientos previos; el registro de restaurante los exige.
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    contact_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    profile_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    banner_image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    manager_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    owner: Mapped["User"] = relationship(back_populates="establishments")
    schedules: Mapped[list["Schedule"]] = relationship(
        back_populates="establishment", cascade="all, delete-orphan", lazy="selectin"
    )
    menu_items: Mapped[list["MenuItem"]] = relationship(
        back_populates="establishment", cascade="all, delete-orphan", lazy="selectin"
    )
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="establishment", cascade="all, delete-orphan", lazy="selectin"
    )
    images: Mapped[list["EstablishmentImage"]] = relationship(
        back_populates="establishment",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="EstablishmentImage.display_order",
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
    image_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_combo: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_available: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    establishment: Mapped[Establishment] = relationship(back_populates="menu_items")
    combo_items: Mapped[list["ComboItem"]] = relationship(
        "ComboItem",
        foreign_keys="[ComboItem.combo_id]",
        back_populates="combo",
        cascade="all, delete-orphan",
        lazy="selectin",
    )


class ComboItem(Base):
    __tablename__ = "combo_items"
    __table_args__ = (CheckConstraint("product_id <> combo_id", name="ck_combo_items_not_self"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    combo_id: Mapped[int] = mapped_column(
        ForeignKey("menu_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("menu_items.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, default=1, nullable=False)

    combo: Mapped["MenuItem"] = relationship("MenuItem", foreign_keys=[combo_id], back_populates="combo_items")
    product: Mapped["MenuItem"] = relationship("MenuItem", foreign_keys=[product_id], lazy="joined")

    @property
    def product_name(self) -> str | None:
        return self.product.name if self.product is not None else None


class EstablishmentImage(Base):
    __tablename__ = "establishment_images"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    establishment_id: Mapped[int] = mapped_column(
        ForeignKey("establishments.id", ondelete="CASCADE"), nullable=False, index=True
    )
    image_url: Mapped[str] = mapped_column(String(500), nullable=False)
    image_type: Mapped[str] = mapped_column(String(20), nullable=False)
    caption: Mapped[str | None] = mapped_column(String(150), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    establishment: Mapped["Establishment"] = relationship(back_populates="images")
