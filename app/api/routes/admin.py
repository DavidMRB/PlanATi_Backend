from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, require_admin
from app.models.establishment import Establishment
from app.models.review import Review
from app.models.user import User
from app.schemas.admin import (
    AdminDashboardResponse,
    AdminEstablishmentDetail,
    AdminEstablishmentListItem,
    EstablishmentDecisionResponse,
    EstablishmentRejectRequest,
    UserRoleUpdate,
)
from app.services.restaurant_service import (
    EstablishmentTransitionError,
    approve_establishment,
    get_establishment_with_owner,
    list_establishments_for_admin,
    reject_establishment,
)
from app.schemas.user import UserResponse

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/dashboard", response_model=AdminDashboardResponse)
async def admin_dashboard(
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> AdminDashboardResponse:
    users_count = await session.scalar(select(func.count()).select_from(User))
    establishments_count = await session.scalar(select(func.count()).select_from(Establishment))
    reviews_count = await session.scalar(select(func.count()).select_from(Review))

    return AdminDashboardResponse(
        users_count=int(users_count or 0),
        establishments_count=int(establishments_count or 0),
        reviews_count=int(reviews_count or 0),
    )


@router.get("/users", response_model=list[UserResponse])
async def list_users(
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[User]:
    result = await session.scalars(select(User).order_by(User.created_at.desc()))
    return list(result.all())


@router.patch("/users/{user_id}/role", response_model=UserResponse)
async def update_user_role(
    user_id: int,
    data: UserRoleUpdate,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")

    normalized_role = data.role.strip().lower()
    if normalized_role not in {"user", "admin"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El rol permitido es 'user' o 'admin'.",
        )

    user.role = normalized_role
    await session.commit()
    await session.refresh(user)
    return user


def _list_item(establishment: Establishment, owner: User) -> AdminEstablishmentListItem:
    return AdminEstablishmentListItem(
        id=establishment.id,
        name=establishment.name,
        category=establishment.category,
        address=establishment.address,
        owner_id=owner.id,
        owner_email=owner.email,
        manager_name=establishment.manager_name,
        phone=establishment.phone,
        contact_email=establishment.contact_email,
        status=establishment.status,
        created_at=establishment.created_at,
    )


async def _get_establishment_or_404(session: AsyncSession, establishment_id: int) -> tuple[Establishment, User]:
    row = await get_establishment_with_owner(session, establishment_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Establecimiento no encontrado")
    return row


@router.get("/establishments", response_model=list[AdminEstablishmentListItem])
async def list_establishments_admin(
    status_filter: Literal["PENDING", "APPROVED", "REJECTED", "ALL"] = Query(default="ALL", alias="status"),
    search: str | None = Query(default=None, max_length=150),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> list[AdminEstablishmentListItem]:
    rows = await list_establishments_for_admin(session, status_filter, search, skip, limit)
    return [_list_item(establishment, owner) for establishment, owner in rows]


@router.get("/establishments/{establishment_id}", response_model=AdminEstablishmentDetail)
async def get_establishment_admin(
    establishment_id: int,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> AdminEstablishmentDetail:
    establishment, owner = await _get_establishment_or_404(session, establishment_id)
    return AdminEstablishmentDetail(
        **_list_item(establishment, owner).model_dump(),
        description=establishment.description,
        rejection_reason=establishment.rejection_reason,
        profile_image_url=establishment.profile_image_url,
        banner_image_url=establishment.banner_image_url,
        owner_full_name=owner.full_name,
        owner_status=owner.status,
        images=establishment.images,
    )


@router.post("/establishments/{establishment_id}/approve", response_model=EstablishmentDecisionResponse)
async def approve_establishment_admin(
    establishment_id: int,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> EstablishmentDecisionResponse:
    establishment, _owner = await _get_establishment_or_404(session, establishment_id)
    try:
        establishment = await approve_establishment(session, establishment)
    except EstablishmentTransitionError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return EstablishmentDecisionResponse(
        id=establishment.id,
        status="APPROVED",
        message="Establecimiento aprobado exitosamente.",
    )


@router.post("/establishments/{establishment_id}/reject", response_model=EstablishmentDecisionResponse)
async def reject_establishment_admin(
    establishment_id: int,
    data: EstablishmentRejectRequest,
    session: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
) -> EstablishmentDecisionResponse:
    establishment, _owner = await _get_establishment_or_404(session, establishment_id)
    try:
        establishment = await reject_establishment(session, establishment, data.reason)
    except EstablishmentTransitionError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
    return EstablishmentDecisionResponse(
        id=establishment.id,
        status="REJECTED",
        rejection_reason=establishment.rejection_reason,
        message="Establecimiento rechazado.",
    )
