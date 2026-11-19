from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.core.security import clear_auth_cookie, verify_password
from app.models.user import User
from app.schemas.privacy import ConsentAcceptRequest, ConsentItem, DeleteAccountRequest
from app.schemas.restaurant import UploadUrlResponse
from app.schemas.auth import PhoneCodeRequest, PhoneVerifyRequest
from app.schemas.user import UserResponse, UserUpdate
from app.services.privacy_service import (
    accept_current_consents,
    delete_account,
    ensure_can_self_delete,
    export_user_data,
    list_consents,
)
from app.services.phone_verification_service import (
    PhoneVerificationError,
    check_account_deletion_code,
    send_account_deletion_code,
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


# --- Privacidad y datos personales (B8, Ley 1581) ------------------------------------------------


@router.get("/me/consents", response_model=list[ConsentItem])
async def get_my_consents(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> list[ConsentItem]:
    """Historial de aceptaciones de la política de datos y los términos (más reciente primero)."""
    return [ConsentItem.model_validate(item) for item in await list_consents(session, current_user.id)]


@router.post("/me/consents", response_model=UserResponse)
async def accept_my_consents(
    request: ConsentAcceptRequest,
    http_request: Request,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> UserResponse:
    """Acepta las versiones vigentes (409 `CONSENT_VERSION_OUTDATED` con `current_versions` si no lo son)."""
    await accept_current_consents(
        session,
        current_user,
        request.privacy_policy_version,
        request.terms_version,
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
    )
    await session.commit()
    await session.refresh(current_user)
    return current_user


@router.get("/me/export")
async def export_my_data(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> JSONResponse:
    """Descarga de "mis datos" en JSON (máximo una cada `DATA_EXPORT_COOLDOWN_MINUTES`, si no 429)."""
    data = await export_user_data(session, current_user)
    await session.commit()
    return JSONResponse(
        content=data,
        headers={
            "Content-Disposition": 'attachment; filename="mis-datos-planati.json"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/me/delete/send-code")
async def send_account_deletion_verification_code(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    """Envía un código SMS al teléfono verificado para confirmar la eliminación (cuentas de Google)."""
    ensure_can_self_delete(current_user)
    try:
        await send_account_deletion_code(session, current_user)
    except PhoneVerificationError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    return {"success": True, "message": "Código de verificación enviado"}


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_account(
    request: DeleteAccountRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Elimina la cuenta (solo rol `user`; `restaurant` y `admin` reciben 409 `SUPPORT_REQUIRED`).

    Borra reseñas (y recalcula los promedios), planes, favoritos y notificaciones, y deja una lápida
    anonimizada para la trazabilidad (ver `privacy_service`). Cierra la sesión.
    """
    ensure_can_self_delete(current_user)
    if request.password is not None:
        if not verify_password(request.password, current_user.password_hash):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Contraseña incorrecta")
    else:
        try:
            await check_account_deletion_code(session, current_user, request.code or "")
        except PhoneVerificationError as error:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    await delete_account(session, current_user)
    await session.commit()
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_auth_cookie(response)
    return response
