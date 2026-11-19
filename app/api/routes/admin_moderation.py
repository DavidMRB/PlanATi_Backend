"""Moderación de contenido, cola de reportes y bitácora (plan de la fase 2, sección 7.5).

Cuándo usar cada acción:
- Insultos, datos personales de terceros, enlaces o publicidad dentro de una opinión real → **bloquear
  comentario** (las estrellas siguen contando).
- Solo una foto es inapropiada → **borrar imagen**.
- Reseña falsa, spam, duplicada con otra cuenta → **ocultar reseña** (sale del promedio).
- Contenido ilegal que no debe quedar ni en la base de datos → **eliminar reseña**.
- Reincidencia → además, **suspender** al autor.

El admin no responde reseñas en nombre del establecimiento; sí puede bloquear sus respuestas.
"""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, require_admin
from app.models.user import User
from app.schemas.admin import (
    AdminReportItem,
    AdminReviewItem,
    BlockCommentRequest,
    BlockReplyRequest,
    DismissReportRequest,
    HideReviewRequest,
    ModerationActionItem,
    ReportTargetPreview,
    ResolveReportRequest,
    RestoreReviewRequest,
    UnblockRequest,
)
from app.schemas.common import Page
from app.schemas.report import ReportReason, ReportTargetType
from app.services import moderation_service, report_service
from app.services.moderation_service import AdminReviewSort

router = APIRouter(prefix="/admin", tags=["admin"])

ReasonQuery = Query(..., min_length=5, max_length=1000, description="Motivo (queda en la bitácora)")


# --- Reseñas ------------------------------------------------------------------------------------


@router.get("/reviews", response_model=Page[AdminReviewItem])
async def list_reviews(
    status_filter: Literal["VISIBLE", "HIDDEN", "ALL"] = Query(default="ALL", alias="status"),
    comment_status: Literal["VISIBLE", "BLOCKED"] | None = Query(default=None),
    flagged_for_review: bool | None = Query(
        default=None, description="Reseñas o respuestas reescritas tras un bloqueo (pendientes de revisión)"
    ),
    establishment_id: int | None = Query(default=None),
    user_id: int | None = Query(default=None),
    rating: int | None = Query(default=None, ge=1, le=5),
    has_reports: bool | None = Query(default=None),
    search: str | None = Query(default=None, max_length=200, description="Texto del comentario"),
    sort: AdminReviewSort = Query(default="recent"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> Page[AdminReviewItem]:
    """Siempre con el texto original, el autor (con email), el local, la respuesta y los reportes abiertos."""
    rows, total = await moderation_service.list_reviews_for_admin(
        session,
        status=status_filter,
        comment_status=comment_status,
        flagged_for_review=flagged_for_review,
        establishment_id=establishment_id,
        user_id=user_id,
        rating=rating,
        has_reports=has_reports,
        search=search,
        sort=sort,
        skip=skip,
        limit=limit,
    )
    items = await moderation_service.admin_review_items(session, rows)
    return Page[AdminReviewItem](items=items, total=total, skip=skip, limit=limit)


@router.post("/reviews/{review_id}/block-comment", response_model=AdminReviewItem)
async def block_comment(
    review_id: int,
    data: BlockCommentRequest,
    session: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> AdminReviewItem:
    """En público el texto se sustituye por el aviso fijo; las estrellas siguen contando."""
    review = await moderation_service.get_review(session, review_id)
    await moderation_service.block_review_comment(
        session, admin, review, category=data.category, note=data.note, remove_images=data.remove_images
    )
    await session.commit()
    return await moderation_service.admin_review_item(session, review_id)


@router.post("/reviews/{review_id}/unblock-comment", response_model=AdminReviewItem)
async def unblock_comment(
    review_id: int,
    data: UnblockRequest | None = None,
    session: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> AdminReviewItem:
    """Publica el comentario; también aprueba un comentario reescrito tras un bloqueo."""
    review = await moderation_service.get_review(session, review_id)
    await moderation_service.unblock_review_comment(session, admin, review, note=data.note if data else None)
    await session.commit()
    return await moderation_service.admin_review_item(session, review_id)


@router.post("/reviews/{review_id}/hide", response_model=AdminReviewItem)
async def hide_review(
    review_id: int,
    data: HideReviewRequest,
    session: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> AdminReviewItem:
    """Retira la reseña entera del público y del promedio (spam, reseña falsa)."""
    review = await moderation_service.get_review(session, review_id)
    await moderation_service.hide_review(session, admin, review, category=data.category, reason=data.reason)
    await session.commit()
    return await moderation_service.admin_review_item(session, review_id)


@router.post("/reviews/{review_id}/restore", response_model=AdminReviewItem)
async def restore_review(
    review_id: int,
    data: RestoreReviewRequest | None = None,
    session: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> AdminReviewItem:
    review = await moderation_service.get_review(session, review_id)
    await moderation_service.restore_review(session, admin, review, note=data.note if data else None)
    await session.commit()
    return await moderation_service.admin_review_item(session, review_id)


@router.delete("/reviews/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review(
    review_id: int,
    reason: str = ReasonQuery,
    session: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> Response:
    """Borrado físico (contenido ilegal). La bitácora guarda una copia del contenido."""
    review = await moderation_service.get_review(session, review_id)
    await moderation_service.delete_review_as_admin(session, admin, review, reason=reason.strip())
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Respuestas e imágenes ----------------------------------------------------------------------


@router.post("/review-replies/{reply_id}/block", response_model=AdminReviewItem)
async def block_reply(
    reply_id: int,
    data: BlockReplyRequest,
    session: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> AdminReviewItem:
    reply = await moderation_service.get_reply(session, reply_id)
    await moderation_service.block_reply(session, admin, reply, category=data.category, note=data.note)
    review_id = reply.review_id
    await session.commit()
    return await moderation_service.admin_review_item(session, review_id)


@router.post("/review-replies/{reply_id}/unblock", response_model=AdminReviewItem)
async def unblock_reply(
    reply_id: int,
    data: UnblockRequest | None = None,
    session: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> AdminReviewItem:
    reply = await moderation_service.get_reply(session, reply_id)
    await moderation_service.unblock_reply(session, admin, reply, note=data.note if data else None)
    review_id = reply.review_id
    await session.commit()
    return await moderation_service.admin_review_item(session, review_id)


@router.delete("/review-images/{image_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_review_image(
    image_id: int,
    reason: str = ReasonQuery,
    session: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> Response:
    image = await moderation_service.get_review_image(session, image_id)
    await moderation_service.delete_review_image(session, admin, image, reason=reason.strip())
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Reportes -----------------------------------------------------------------------------------


def _report_item(report, reporter: User | None, on_target: int, target) -> AdminReportItem:
    preview = (
        ReportTargetPreview(
            exists=True,
            visible=target.visible,
            owner_id=target.owner_id,
            establishment_id=target.establishment_id,
            **target.preview,
        )
        if target is not None
        else ReportTargetPreview(exists=False)
    )
    return AdminReportItem(
        id=report.id,
        reporter_id=report.reporter_id,
        reporter_name=reporter.full_name if reporter else None,
        reporter_email=reporter.email if reporter else None,
        target_type=report.target_type,
        target_id=report.target_id,
        reason=report.reason,
        details=report.details,
        status=report.status,
        created_at=report.created_at,
        resolved_at=report.resolved_at,
        resolved_by_id=report.resolved_by_id,
        resolution_note=report.resolution_note,
        reports_on_target=on_target,
        preview=preview,
    )


async def _single_report_item(session: AsyncSession, report_id: int) -> AdminReportItem:
    report = await report_service.get_report(session, report_id)
    reporter = await session.get(User, report.reporter_id)
    on_target = await report_service.count_open_reports(session, report.target_type, report.target_id)
    target = await report_service.load_target(session, report.target_type, report.target_id)
    return _report_item(report, reporter, on_target, target)


@router.get("/reports", response_model=Page[AdminReportItem])
async def list_reports(
    status_filter: Literal["OPEN", "RESOLVED", "DISMISSED", "ALL"] = Query(default="OPEN", alias="status"),
    target_type: ReportTargetType | None = Query(default=None),
    reason: ReportReason | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> Page[AdminReportItem]:
    rows, total = await report_service.list_reports(
        session, status=status_filter, target_type=target_type, reason=reason, skip=skip, limit=limit
    )
    return Page[AdminReportItem](items=[_report_item(*row) for row in rows], total=total, skip=skip, limit=limit)


@router.post("/reports/{report_id}/resolve", response_model=AdminReportItem)
async def resolve_report(
    report_id: int,
    data: ResolveReportRequest,
    session: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> AdminReportItem:
    """Aplica la acción según el tipo de destino, resuelve TODOS los reportes abiertos del mismo
    destino y avisa a quienes reportaron y al responsable del contenido."""
    await report_service.resolve_report(session, admin, report_id, data.action, data.category, data.note)
    return await _single_report_item(session, report_id)


@router.post("/reports/{report_id}/dismiss", response_model=AdminReportItem)
async def dismiss_report(
    report_id: int,
    data: DismissReportRequest | None = None,
    session: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> AdminReportItem:
    """Descarta todos los reportes abiertos del mismo destino."""
    await report_service.dismiss_report(session, admin, report_id, data.note if data else None)
    return await _single_report_item(session, report_id)


# --- Bitácora -----------------------------------------------------------------------------------


@router.get("/moderation-actions", response_model=Page[ModerationActionItem])
async def list_moderation_actions(
    admin_id: int | None = Query(default=None),
    action: str | None = Query(default=None, max_length=40),
    target_type: str | None = Query(default=None, max_length=30),
    target_id: int | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> Page[ModerationActionItem]:
    rows, total = await moderation_service.list_moderation_actions(
        session,
        admin_id=admin_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        skip=skip,
        limit=limit,
    )
    items = [moderation_service.to_moderation_action_item(entry, admin) for entry, admin in rows]
    return Page[ModerationActionItem](items=items, total=total, skip=skip, limit=limit)
