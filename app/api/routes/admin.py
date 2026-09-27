from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, require_admin
from app.models.establishment import Establishment
from app.models.review import Review
from app.models.user import User
from app.schemas.admin import AdminDashboardResponse, UserRoleUpdate
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
