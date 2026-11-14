from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import ensure_not_suspended, get_current_user, get_db
from app.core.config import settings
from app.core.security import (
    OAUTH_STATE_COOKIE_NAME,
    clear_auth_cookie,
    clear_oauth_state_cookie,
    create_oauth_state,
    csrf_claim,
    new_csrf_token,
    set_auth_cookie,
    set_oauth_state_cookie,
    verify_oauth_state,
)
from app.integrations.google import GoogleOAuthClient, GoogleOAuthError
from app.models.user import User
from app.schemas.auth import (
    AuthResponse,
    CsrfTokenResponse,
    GoogleExchangeRequest,
    LoginRequest,
    PhoneCodeRequest,
    PhoneVerificationResponse,
    PhoneVerifyRequest,
    RegisterRequest,
)
from app.schemas.restaurant import RestaurantRegisterRequest, RestaurantRegisterResponse
from app.services.establishment_service import OutOfServiceAreaError
from app.services.auth_service import (
    ConsentContext,
    authenticate_google_user,
    authenticate_user,
    consume_oauth_login_code,
    get_owned_establishment_status,
    issue_access_token,
    issue_oauth_login_code,
    register_restaurant,
    register_user,
)
from app.services.privacy_service import check_versions
from app.services.phone_verification_service import (
    PhoneVerificationError,
    send_phone_code,
    verify_phone_code,
)

router = APIRouter(prefix="/auth", tags=["auth"])
google_client = GoogleOAuthClient()


def consent_context(http_request: Request) -> ConsentContext:
    """IP y user agent de quien acepta: solo se guardan en `consents`, como prueba de la autorización."""
    return ConsentContext(
        ip_address=http_request.client.host if http_request.client else None,
        user_agent=http_request.headers.get("user-agent"),
    )


def start_session(response: Response, user: User) -> str:
    """Emite el JWT en la cookie HttpOnly y devuelve el token CSRF de esa sesión."""
    csrf_token = new_csrf_token()
    set_auth_cookie(response, issue_access_token(user, csrf_token=csrf_token))
    return csrf_token


@router.get("/google")
async def google_login(response: Response) -> dict[str, str]:
    try:
        oauth_state = create_oauth_state()
        set_oauth_state_cookie(response, oauth_state)
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
    if request.cookies.get(OAUTH_STATE_COOKIE_NAME) != state or not verify_oauth_state(state):
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
    clear_oauth_state_cookie(redirect_response)
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

    ensure_not_suspended(user)
    csrf_token = start_session(response, user)
    complete = user.phone_verified and user.status == "ACTIVE"
    return AuthResponse(
        registration_complete=complete,
        requires_phone_verification=not complete,
        role=user.role,
        establishment_status=await get_owned_establishment_status(session, user),
        csrf_token=csrf_token,
    )


@router.get("/csrf", response_model=CsrfTokenResponse)
async def get_csrf_token(
    request: Request,
    response: Response,
    _: User = Depends(get_current_user),
) -> CsrfTokenResponse:
    """Devuelve el token CSRF de la sesión actual; el frontend lo pide al recargar la página."""
    csrf_token = csrf_claim(request.cookies.get(settings.access_token_cookie_name))
    if csrf_token is None:
        # Sesión sin cookie (solo Bearer) o emitida antes de activar CSRF: hay que iniciar sesión de nuevo.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Tu sesión expiró. Inicia sesión de nuevo.",
        )
    response.headers["Cache-Control"] = "no-store"
    return CsrfTokenResponse(csrf_token=csrf_token)


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
    http_request: Request,
    session: AsyncSession = Depends(get_db),
) -> AuthResponse:
    # 409 CONSENT_VERSION_OUTDATED si el formulario se cargó con una versión anterior de los textos.
    check_versions(request.privacy_policy_version, request.terms_version)
    try:
        user = await register_user(
            session,
            full_name=request.full_name,
            nickname=request.nickname,
            phone_number=request.phone_number,
            email=request.email,
            password=request.password,
            consent=consent_context(http_request),
        )
        await send_phone_code(session, user, request.phone_number)
    except (PhoneVerificationError, ValueError) as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    csrf_token = start_session(response, user)
    complete = user.phone_verified and user.status == "ACTIVE"
    return AuthResponse(
        registration_complete=complete,
        requires_phone_verification=not complete,
        role=user.role,
        establishment_status=await get_owned_establishment_status(session, user),
        csrf_token=csrf_token,
    )


@router.post(
    "/restaurant/register",
    response_model=RestaurantRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_restaurant_account(
    request: RestaurantRegisterRequest,
    response: Response,
    http_request: Request,
    session: AsyncSession = Depends(get_db),
) -> RestaurantRegisterResponse:
    check_versions(request.privacy_policy_version, request.terms_version)
    fields = request.model_dump(
        exclude={"accept_privacy_policy", "accept_terms", "privacy_policy_version", "terms_version"}
    )
    try:
        user, establishment = await register_restaurant(session, **fields, consent=consent_context(http_request))
    except OutOfServiceAreaError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error

    csrf_token = start_session(response, user)
    return RestaurantRegisterResponse(
        user_id=user.id,
        establishment_id=establishment.id,
        role=user.role,
        establishment_status=establishment.status,
        message="Solicitud de registro enviada con éxito. Pendiente de aprobación.",
        csrf_token=csrf_token,
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

    # Solo tras comprobar la contraseña: no revela a terceros que la cuenta existe y está suspendida.
    ensure_not_suspended(user)
    csrf_token = start_session(response, user)
    complete = user.phone_verified and user.status == "ACTIVE"
    return AuthResponse(
        registration_complete=complete,
        requires_phone_verification=not complete,
        role=user.role,
        establishment_status=await get_owned_establishment_status(session, user),
        csrf_token=csrf_token,
    )
