from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, require_active_user
from app.models.report import Report
from app.models.user import User
from app.schemas.report import ReportCreate, ReportResponse
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["reports"])


@router.post("", response_model=ReportResponse, status_code=status.HTTP_201_CREATED)
async def create_report(
    data: ReportCreate,
    current_user: User = Depends(require_active_user),
    session: AsyncSession = Depends(get_db),
) -> Report:
    """Reporta contenido visible que no es tuyo (también los establecimientos, p. ej. una reseña falsa).

    404 si no existe o no es visible; 400 si es propio; 409 si ya lo reportaste; 429 al superar el
    límite diario.
    """
    return await report_service.create_report(
        session, current_user, data.target_type, data.target_id, data.reason, data.details
    )
