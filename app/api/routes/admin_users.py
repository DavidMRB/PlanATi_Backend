"""Gestión de usuarios desde la consola admin (plan de la fase 2, sección 7.5)."""

from typing import Literal

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, require_admin
from app.models.establishment import Establishment
from app.models.report import Report
from app.models.review import Review
from app.models.user import User
from app.schemas.admin import (
    AdminNotifyRequest,
    AdminUserDetail,
    AdminUserEstablishment,
    AdminUserListItem,
    ReactivateRequest,
    ReportSummary,
    SuspendRequest,
    UserRoleUpdate,
)
from app.schemas.common import Page
from app.services import admin_service, moderation_service, report_service

router = APIRouter(prefix="/admin/users", tags=["admin"])


def _list_item(user: User, reviews: int, reports: int, establishment_id: int | None) -> AdminUserListItem:
    item = AdminUserListItem.model_validate(user, from_attributes=True)
    return item.model_copy(
        update={"reviews_count": reviews, "open_reports_count": reports, "establishment_id": establishment_id}
    )


async def _item(session: AsyncSession, user: User) -> AdminUserListItem:
    return _list_item(user, *await admin_service.user_counts(session, user.id))


@router.get("", response_model=Page[AdminUserListItem])
async def list_users(
    search: str | None = Query(default=None, max_length=150, description="Nombre, apodo, email o teléfono"),
    role: Literal["user", "admin", "restaurant"] | None = Query(default=None),
    status_filter: Literal["PENDING_PHONE", "ACTIVE", "SUSPENDED", "DELETED"] | None = Query(
        default=None, alias="status", description="Sin filtro no se listan las cuentas eliminadas (DELETED)"
    ),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> Page[AdminUserListItem]:
    rows, total = await admin_service.list_users(
        session, search=search, role=role, status=status_filter, skip=skip, limit=limit
    )
    return Page[AdminUserListItem](items=[_list_item(*row) for row in rows], total=total, skip=skip, limit=limit)


@router.get("/{user_id}", response_model=AdminUserDetail)
async def get_user_detail(
    user_id: int,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> AdminUserDetail:
    """Perfil, conteos, establecimientos, últimas 10 reseñas, reportes recibidos y acciones de moderación."""
    user = await admin_service.get_user(session, user_id)
    base = await _item(session, user)
    establishments = (
        await session.scalars(select(Establishment).where(Establishment.owner_id == user.id).order_by(Establishment.id))
    ).all()
    review_rows, _total = await moderation_service.list_reviews_for_admin(session, user_id=user.id, limit=10)
    reports = await report_service.reports_about(
        session,
        [
            or_(
                and_(Report.target_type == "USER", Report.target_id == user.id),
                and_(
                    Report.target_type == "REVIEW",
                    Report.target_id.in_(select(Review.id).where(Review.user_id == user.id)),
                ),
            )
        ],
    )
    history, _ = await moderation_service.list_moderation_actions(
        session, target_type="USER", target_id=user.id, limit=10
    )
    return AdminUserDetail(
        **base.model_dump(),
        establishments=[AdminUserEstablishment.model_validate(e) for e in establishments],
        recent_reviews=await moderation_service.admin_review_items(session, review_rows),
        reports_received=[ReportSummary.model_validate(report) for report in reports],
        moderation_history=[moderation_service.to_moderation_action_item(entry, admin) for entry, admin in history],
    )


@router.patch("/{user_id}/role", response_model=AdminUserListItem)
async def update_user_role(
    user_id: int,
    data: UserRoleUpdate,
    session: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> AdminUserListItem:
    """`user` ↔ `admin`. No sobre uno mismo, ni sobre cuentas `restaurant`, ni dejando el sistema sin admins (400)."""
    user = await admin_service.get_user(session, user_id)
    await admin_service.change_role(session, admin, user, data.role)
    await session.commit()
    return await _item(session, user)


@router.post("/{user_id}/suspend", response_model=AdminUserListItem)
async def suspend_user(
    user_id: int,
    data: SuspendRequest,
    session: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> AdminUserListItem:
    """Su sesión deja de servir de inmediato (403 `ACCOUNT_SUSPENDED`). Para una cuenta `restaurant`
    la respuesta trae `establishment_id`, para ofrecer suspender también el local."""
    user = await admin_service.get_user(session, user_id)
    await admin_service.suspend_user(session, admin, user, data.reason)
    await session.commit()
    return await _item(session, user)


@router.post("/{user_id}/reactivate", response_model=AdminUserListItem)
async def reactivate_user(
    user_id: int,
    data: ReactivateRequest | None = None,
    session: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> AdminUserListItem:
    """Vuelve a ACTIVE (o a PENDING_PHONE si nunca verificó su teléfono)."""
    user = await admin_service.get_user(session, user_id)
    await admin_service.reactivate_user(session, admin, user, data.note if data else None)
    await session.commit()
    return await _item(session, user)


@router.post("/{user_id}/notify", status_code=status.HTTP_204_NO_CONTENT)
async def notify_user(
    user_id: int,
    data: AdminNotifyRequest,
    session: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
) -> Response:
    """Aviso manual (`ADMIN_MESSAGE`) en la bandeja del usuario."""
    user = await admin_service.get_user(session, user_id)
    await admin_service.send_admin_message(session, admin, user, title=data.title, body=data.body, link=data.link)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

