from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.user import UserResponse, UserUpdate
from app.services.phone_verification_service import PhoneVerificationError, set_phone_number

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)) -> UserResponse:
    return current_user


@router.patch("/me", response_model=UserResponse)
async def update_me(
    request: UserUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> UserResponse:
    if request.full_name is not None:
        current_user.full_name = request.full_name.strip()
    if request.nickname is not None:
        current_user.nickname = request.nickname.strip()
    if request.picture is not None:
        current_user.picture = request.picture.strip() or None
    if request.phone_number is not None:
        try:
            await set_phone_number(session, current_user, request.phone_number)
        except PhoneVerificationError as error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    await session.commit()
    await session.refresh(current_user)
    return current_user
