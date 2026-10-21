from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.dependencies import EstablishmentAccessError

from app.api.routes.health import router as health_router
from app.api.routes.admin import router as admin_router
from app.api.routes.auth import router as auth_router
from app.api.routes.establishments import router as establishments_router
from app.api.routes.restaurant import router as restaurant_router
from app.api.routes.reviews import router as reviews_router
from app.api.routes.users import router as users_router
from app.core.config import settings

app = FastAPI(title=settings.app_name)


@app.exception_handler(EstablishmentAccessError)
async def establishment_access_error_handler(_: Request, error: EstablishmentAccessError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"detail": error.detail, "status": error.status},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, prefix=settings.api_v1_prefix)
app.include_router(auth_router, prefix=settings.api_v1_prefix)
app.include_router(users_router, prefix=settings.api_v1_prefix)
app.include_router(establishments_router, prefix=settings.api_v1_prefix)
app.include_router(reviews_router, prefix=settings.api_v1_prefix)
app.include_router(admin_router, prefix=settings.api_v1_prefix)
app.include_router(restaurant_router, prefix=settings.api_v1_prefix)
