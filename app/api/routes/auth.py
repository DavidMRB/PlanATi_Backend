from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.core.config import settings
from app.core.security import create_oauth_state, verify_oauth_state
from app.integrations.google import GoogleOAuthClient, GoogleOAuthError
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    PhoneCodeRequest,
    PhoneVerificationResponse,
    PhoneVerifyRequest,
    RegisterRequest,
    TokenResponse,
)
from app.services.auth_service import (
    authenticate_google_user,
    authenticate_user,
    issue_access_token,
    register_user,
)
from app.services.phone_verification_service import (
    PhoneVerificationError,
    send_phone_code,
    verify_phone_code,
)

router = APIRouter(prefix="/auth", tags=["auth"])
google_client = GoogleOAuthClient()


@router.get("/google")
async def google_login(response: Response) -> dict[str, str]:
    try:
        oauth_state = create_oauth_state()
        response.set_cookie(
            "oauth_state",
            oauth_state,
            httponly=True,
            secure=settings.app_env == "production",
            samesite="lax",
            max_age=600,
        )
        return {"authorization_url": google_client.authorization_url(oauth_state)}
    except GoogleOAuthError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error


@router.get("/google/callback")
async def google_callback(
    request: Request,
    response: Response,
    code: str = Query(...),
    state: str = Query(...),
    session: AsyncSession = Depends(get_db),
) -> Response:
    if request.cookies.get("oauth_state") != state or not verify_oauth_state(state):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Estado OAuth inválido")
    try:
        identity = await google_client.authenticate_code(code)
        user, access_token = await authenticate_google_user(session, identity)
    except (GoogleOAuthError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error
    complete = user.phone_verified and user.status == "ACTIVE"
    redirect_params = urlencode(
        {
            "access_token": access_token,
            "registration_complete": str(complete).lower(),
            "requires_phone_verification": str(not complete).lower(),
        }
    )
    redirect_response = RedirectResponse(
        url=f"{settings.frontend_url.rstrip('/')}/google-callback?{redirect_params}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    redirect_response.delete_cookie("oauth_state")
    return redirect_response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout() -> None:
    return None


@router.post("/phone/send-code")
async def send_phone_verification_code(
    request: PhoneCodeRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, object]:
    try:
        await send_phone_code(session, current_user, request.phone_number)
    except PhoneVerificationError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    return {"success": True, "message": "Verification code sent"}


@router.post("/phone/verify", response_model=PhoneVerificationResponse)
async def verify_phone_verification_code(
    request: PhoneVerifyRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> PhoneVerificationResponse:
    try:
        await verify_phone_code(session, current_user, request.phone_number, request.code)
    except PhoneVerificationError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    return PhoneVerificationResponse()


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(request: RegisterRequest, session: AsyncSession = Depends(get_db)) -> TokenResponse:
    try:
        user = await register_user(
            session,
            full_name=request.full_name,
            nickname=request.nickname,
            phone_number=request.phone_number,
            email=request.email,
            password=request.password,
        )
        await send_phone_code(session, user, request.phone_number)
    except (PhoneVerificationError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    complete = user.phone_verified and user.status == "ACTIVE"
    return TokenResponse(
        access_token=issue_access_token(user),
        registration_complete=complete,
        requires_phone_verification=not complete,
    )


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, session: AsyncSession = Depends(get_db)) -> TokenResponse:
    user = await authenticate_user(session, request.email, request.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales invalidas",
        )
    complete = user.phone_verified and user.status == "ACTIVE"
    return TokenResponse(
        access_token=issue_access_token(user),
        registration_complete=complete,
        requires_phone_verification=not complete,
    )
