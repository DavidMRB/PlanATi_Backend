from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base

REPORT_TARGETS = {
    "REVIEW",
    "REVIEW_REPLY",
    "REVIEW_IMAGE",
    "ESTABLISHMENT",
    "ESTABLISHMENT_IMAGE",
    "MENU_ITEM",
    "USER",
}
REPORT_REASONS = {"SPAM", "OFFENSIVE", "FALSE_INFO", "INAPPROPRIATE_IMAGE", "OTHER"}
REPORT_STATUSES = {"OPEN", "RESOLVED", "DISMISSED"}


class Report(Base):
    """Reporte de un usuario sobre contenido. El destino es polimórfico (sin FK):
    `report_service.resolve_target` valida que exista y sea visible para quien reporta."""

    __tablename__ = "reports"
    __table_args__ = (
        UniqueConstraint("reporter_id", "target_type", "target_id", name="uq_reports_reporter_target"),
        Index("ix_reports_status_target", "status", "target_type", "target_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    reporter_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(30), nullable=False)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", server_default="OPEN", nullable=False)
    resolved_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
