import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.dependencies import AccountSuspendedError, EstablishmentAccessError

from app.api.routes.health import router as health_router
from app.api.routes.admin import router as admin_router
from app.api.routes.admin_moderation import router as admin_moderation_router
from app.api.routes.admin_users import router as admin_users_router
from app.api.routes.auth import router as auth_router
from app.api.routes.establishments import router as establishments_router
from app.api.routes.favorites import router as favorites_router
from app.api.routes.legal import router as legal_router
from app.api.routes.notifications import router as notifications_router
from app.api.routes.plans import router as plans_router
from app.api.routes.reports import router as reports_router
from app.api.routes.restaurant import router as restaurant_router
from app.api.routes.reviews import router as reviews_router
from app.api.routes.users import router as users_router
from app.core.config import settings
from app.core.csrf import CSRF_HEADER_NAME, CsrfError, csrf_protect
from app.core.log_filters import install_log_filters
from app.core.startup_checks import enforce_settings
from app.workers.reminders import reminders_loop
from app.services.favorite_service import FavoriteError
from app.services.moderation_service import ModerationError
from app.services.plan_service import PlanError
from app.services.privacy_service import PrivacyError
from app.services.review_service import ReviewError


# GUIA #10 TEMA: Subalgoritmos (funciones, procedimientos y modularización) -> Uvicorn arranca esta app y `lifespan` controla el inicio y el cierre
# (reemplaza a `if __name__ == "__main__"` + `iniciar_programa()` de los ejemplos de consola).
@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # En producción no arranca con una configuración insegura (clave débil, mock SMS, http://…).
    enforce_settings(settings)
    install_log_filters()
    stop = asyncio.Event()
    # Recordatorios de planes, cierre de planes pasados y purga de notificaciones (idempotente).
    task = asyncio.create_task(reminders_loop(stop)) if settings.reminders_enabled else None
    try:
        yield
    finally:
        if task is not None:
            stop.set()
            await task


install_log_filters()
_docs_enabled = settings.api_docs_enabled
app = FastAPI(
    title=settings.app_name,
    lifespan=lifespan,
    dependencies=[Depends(csrf_protect)],
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)


@app.exception_handler(EstablishmentAccessError)
async def establishment_access_error_handler(_: Request, error: EstablishmentAccessError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"detail": error.detail, "status": error.status},
    )


@app.exception_handler(AccountSuspendedError)
async def account_suspended_handler(_: Request, error: AccountSuspendedError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"detail": error.detail, "code": error.code, "reason": error.reason},
    )


@app.exception_handler(ModerationError)
async def moderation_error_handler(_: Request, error: ModerationError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content={"detail": error.detail, **error.extra})


@app.exception_handler(PlanError)
async def plan_error_handler(_: Request, error: PlanError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content={"detail": error.detail, **error.extra})


@app.exception_handler(FavoriteError)
async def favorite_error_handler(_: Request, error: FavoriteError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content={"detail": error.detail, **error.extra})


@app.exception_handler(PrivacyError)
async def privacy_error_handler(_: Request, error: PrivacyError) -> JSONResponse:
    # `code`: CONSENT_REQUIRED (403), CONSENT_VERSION_OUTDATED (409, con `current_versions`), SUPPORT_REQUIRED (409)…
    return JSONResponse(status_code=error.status_code, content={"detail": error.detail, **error.extra})


@app.exception_handler(ReviewError)
async def review_error_handler(_: Request, error: ReviewError) -> JSONResponse:
    # `extra` lleva datos para el frontend, p. ej. {"review_id": n} en el 409 o {"code": "OWNER"} en el 403.
    return JSONResponse(status_code=error.status_code, content={"detail": error.detail, **error.extra})


@app.exception_handler(CsrfError)
async def csrf_error_handler(_: Request, error: CsrfError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"detail": error.detail, "code": error.code},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    # En producción, métodos y cabeceras explícitos (sección 9.1 del plan de la fase 2).
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"] if settings.is_production else ["*"],
    allow_headers=["Content-Type", CSRF_HEADER_NAME, "Authorization"] if settings.is_production else ["*"],
)

# GUIA #6 TEMA: Ciclos -> no hay un menú `while True`: Uvicorn mantiene su propio ciclo de peticiones
# y cada opción del menú es una ruta registrada aquí con `include_router`.
app.include_router(health_router, prefix=settings.api_v1_prefix)
app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(users_router, prefix=settings.api_v1_prefix)
app.include_router(establishments_router, prefix=settings.api_v1_prefix)
app.include_router(reviews_router, prefix=settings.api_v1_prefix)
app.include_router(admin_router, prefix=settings.api_v1_prefix)
app.include_router(admin_users_router, prefix=settings.api_v1_prefix)
app.include_router(admin_moderation_router, prefix=settings.api_v1_prefix)
app.include_router(restaurant_router, prefix=settings.api_v1_prefix)
app.include_router(notifications_router, prefix=settings.api_v1_prefix)
app.include_router(reports_router, prefix=settings.api_v1_prefix)
app.include_router(plans_router, prefix=settings.api_v1_prefix)
app.include_router(favorites_router, prefix=settings.api_v1_prefix)
app.include_router(legal_router, prefix=settings.api_v1_prefix)
