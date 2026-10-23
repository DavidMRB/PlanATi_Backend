from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.restaurant import UploadUrlResponse
from app.schemas.auth import PhoneCodeRequest, PhoneVerifyRequest
from app.schemas.user import UserResponse, UserUpdate
from app.services.phone_verification_service import (
    PhoneVerificationError,
    normalize_colombian_phone,
    send_phone_change_code,
    set_phone_number,
    verify_phone_code,
)
from app.services.storage import build_avatar_upload_url

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
            # Con un teléfono ya verificado, cambiarlo exige confirmar el nuevo por SMS antes de aplicarlo.
            if (
                current_user.phone_verified
                and normalize_colombian_phone(request.phone_number) != current_user.phone_number
            ):
                raise PhoneVerificationError(
                    "Para cambiar tu teléfono verifica el nuevo número por SMS desde Mi perfil"
                )
            await set_phone_number(session, current_user, request.phone_number)
        except PhoneVerificationError as error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    await session.commit()
    await session.refresh(current_user)
    return current_user


@router.post("/me/upload-url", response_model=UploadUrlResponse)
async def create_avatar_upload_url(
    file_extension: str = Query(default=".jpg", max_length=6),
    _: User = Depends(get_current_user),
) -> dict[str, str]:
    # Disponible desde el registro: la foto se elige al completar el perfil, antes de verificar el teléfono.
    return build_avatar_upload_url(file_extension)


@router.post("/me/phone/send-code")
async def send_phone_change_verification_code(
    request: PhoneCodeRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    try:
        await send_phone_change_code(session, current_user, request.phone_number)
    except PhoneVerificationError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    return {"success": True, "message": "Código de verificación enviado"}


@router.post("/me/phone/verify", response_model=UserResponse)
async def verify_phone_change(
    request: PhoneVerifyRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> UserResponse:
    try:
        await verify_phone_code(session, current_user, request.phone_number, request.code)
    except PhoneVerificationError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    return current_user
