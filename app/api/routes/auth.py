from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_current_user, get_db
from app.core.config import settings
from app.core.security import clear_auth_cookie, create_oauth_state, set_auth_cookie, verify_oauth_state
from app.integrations.google import GoogleOAuthClient, GoogleOAuthError
from app.models.user import User
from app.schemas.auth import (
    AuthResponse,
    GoogleExchangeRequest,
    LoginRequest,
    PhoneCodeRequest,
    PhoneVerificationResponse,
    PhoneVerifyRequest,
    RegisterRequest,
)
from app.schemas.restaurant import RestaurantRegisterRequest, RestaurantRegisterResponse
from app.services.auth_service import (
    authenticate_google_user,
    authenticate_user,
    consume_oauth_login_code,
    get_owned_establishment_status,
    issue_access_token,
    issue_oauth_login_code,
    register_restaurant,
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
    code: str = Query(...),
    state: str = Query(...),
    session: AsyncSession = Depends(get_db),
) -> Response:
    if request.cookies.get("oauth_state") != state or not verify_oauth_state(state):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Estado OAuth inválido")
    try:
        identity = await google_client.authenticate_code(code)
        user, _ = await authenticate_google_user(session, identity)
        temp_code = await issue_oauth_login_code(session, user)
    except (GoogleOAuthError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error

    redirect_response = RedirectResponse(
        url=f"{settings.frontend_url.rstrip('/')}/google-callback?code={temp_code}",
        status_code=status.HTTP_303_SEE_OTHER,
    )
    redirect_response.delete_cookie("oauth_state")
    return redirect_response


@router.post("/google/exchange", response_model=AuthResponse)
async def google_exchange(
    request: GoogleExchangeRequest,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> AuthResponse:
    try:
        user = await consume_oauth_login_code(session, request.code)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(error)) from error

    access_token = issue_access_token(user)
    set_auth_cookie(response, access_token)
    complete = user.phone_verified and user.status == "ACTIVE"
    return AuthResponse(
        registration_complete=complete,
        requires_phone_verification=not complete,
        role=user.role,
        establishment_status=await get_owned_establishment_status(session, user),
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(response: Response) -> None:
    clear_auth_cookie(response)
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


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
async def register(
    request: RegisterRequest,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> AuthResponse:
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

    access_token = issue_access_token(user)
    set_auth_cookie(response, access_token)
    complete = user.phone_verified and user.status == "ACTIVE"
    return AuthResponse(
        registration_complete=complete,
        requires_phone_verification=not complete,
        role=user.role,
        establishment_status=await get_owned_establishment_status(session, user),
    )


@router.post(
    "/restaurant/register",
    response_model=RestaurantRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_restaurant_account(
    request: RestaurantRegisterRequest,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> RestaurantRegisterResponse:
    try:
        user, establishment = await register_restaurant(session, **request.model_dump())
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    set_auth_cookie(response, issue_access_token(user))
    return RestaurantRegisterResponse(
        user_id=user.id,
        establishment_id=establishment.id,
        role=user.role,
        establishment_status=establishment.status,
        message="Solicitud de registro enviada con éxito. Pendiente de aprobación.",
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    request: LoginRequest,
    response: Response,
    session: AsyncSession = Depends(get_db),
) -> AuthResponse:
    user = await authenticate_user(session, request.email, request.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales invalidas",
        )

    access_token = issue_access_token(user)
    set_auth_cookie(response, access_token)
    complete = user.phone_verified and user.status == "ACTIVE"
    return AuthResponse(
        registration_complete=complete,
        requires_phone_verification=not complete,
        role=user.role,
        establishment_status=await get_owned_establishment_status(session, user),
    )
