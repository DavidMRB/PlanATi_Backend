from fastapi import APIRouter

from app.schemas.privacy import LegalVersionsResponse
from app.services.privacy_service import current_versions

router = APIRouter(prefix="/legal", tags=["legal"])


@router.get("/versions", response_model=LegalVersionsResponse)
async def get_legal_versions() -> LegalVersionsResponse:
    """Versiones vigentes de la política de tratamiento de datos y de los términos (público)."""
    return LegalVersionsResponse(**current_versions())
