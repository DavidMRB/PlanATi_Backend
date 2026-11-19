from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

# SCHEDULED: programado; CANCELLED: cancelado por el usuario (queda en el historial);
# COMPLETED: ya pasó (lo marca `reminder_service.complete_past_plans`).
PLAN_STATUSES = {"SCHEDULED", "CANCELLED", "COMPLETED"}
REMINDER_OPTIONS = (15, 30, 60, 120, 1440)


class Plan(Base):
    """Visita agendada por un usuario (personal: el establecimiento no la confirma, decisión D1)."""

    __tablename__ = "plans"
    __table_args__ = (
        Index("ix_plans_user_scheduled", "user_id", "scheduled_at"),
        Index("ix_plans_reminder_due", "status", "reminder_at", "reminder_sent_at"),
        Index("ix_plans_establishment_status", "establishment_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    establishment_id: Mapped[int] = mapped_column(
        ForeignKey("establishments.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Siempre en UTC (ver app/core/time.py).
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    party_size: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="SCHEDULED", server_default="SCHEDULED", nullable=False)
    # None = sin recordatorio.
    reminder_minutes_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reminder_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reminder_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Calculado en el servidor con los precios del catálogo al planear (nunca lo envía el cliente).
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), server_default="0", nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="COP", server_default="COP", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    items: Mapped[list["PlanItem"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", lazy="selectin", order_by="PlanItem.id"
    )


class PlanItem(Base):
    """Plato o combo del plan. Nombre y precio se congelan (snapshot) al planear: si el local cambia
    el precio o borra el producto, el plan sigue legible y su total no cambia sin que el usuario lo sepa."""

    __tablename__ = "plan_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True)
    # SET NULL: el restaurante puede borrar el producto.
    menu_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("menu_items.id", ondelete="SET NULL"), nullable=True
    )
    name_snapshot: Mapped[str] = mapped_column(String(120), nullable=False)
    unit_price_snapshot: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    notes: Mapped[str | None] = mapped_column(String(200), nullable=True)

    plan: Mapped[Plan] = relationship(back_populates="items")
