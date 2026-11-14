"""Planes del usuario: agendar visitas, verlas en un calendario y exportarlas (`.ics`)."""

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import AwareDatetime
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_db, require_planner
from app.models.establishment import Establishment
from app.models.user import User
from app.schemas.common import Page
from app.schemas.plan import PlanCreate, PlanDetail, PlanListItem, PlanStatus, PlanUpdate
from app.services import plan_service
from app.services.calendar_service import build_plan_ics

router = APIRouter(prefix="/plans", tags=["plans"])


@router.post("", response_model=PlanDetail, status_code=status.HTTP_201_CREATED)
async def create_plan(
    data: PlanCreate,
    user: User = Depends(require_planner),
    session: AsyncSession = Depends(get_db),
) -> PlanDetail:
    """El total se calcula en el servidor con los precios actuales. 400 si el local está cerrado a esa
    hora, hay platos inválidos o el recordatorio quedaría en el pasado; 404 si el local no está
    aprobado; 429 al superar `PLAN_MAX_ACTIVE` planes programados."""
    plan = await plan_service.create_plan(session, user, data)
    return await plan_service.to_plan_detail(session, plan)


@router.get("", response_model=Page[PlanListItem])
async def list_plans(
    date_from: AwareDatetime | None = Query(default=None, alias="from", description="ISO con zona horaria"),
    date_to: AwareDatetime | None = Query(default=None, alias="to", description="ISO con zona; máx. 92 días"),
    status_filter: PlanStatus | None = Query(default=None, alias="status"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    user: User = Depends(require_planner),
    session: AsyncSession = Depends(get_db),
) -> Page[PlanListItem]:
    """Con `from` y `to`: los planes de ese rango (para el calendario). Sin ellos: los próximos."""
    plans, total = await plan_service.list_plans(
        session, user, date_from=date_from, date_to=date_to, status=status_filter, skip=skip, limit=limit
    )
    items = await plan_service.to_plan_list_items(session, plans)
    return Page[PlanListItem](items=items, total=total, skip=skip, limit=limit)


@router.get("/{plan_id}", response_model=PlanDetail)
async def get_plan(
    plan_id: int,
    user: User = Depends(require_planner),
    session: AsyncSession = Depends(get_db),
) -> PlanDetail:
    plan = await plan_service.get_own_plan(session, user, plan_id)
    return await plan_service.to_plan_detail(session, plan)


@router.patch("/{plan_id}", response_model=PlanDetail)
async def update_plan(
    plan_id: int,
    data: PlanUpdate,
    user: User = Depends(require_planner),
    session: AsyncSession = Depends(get_db),
) -> PlanDetail:
    """Solo planes programados y futuros (409). `items` reemplaza la lista y recalcula el total con los
    precios actuales; cambiar la fecha o el recordatorio reprograma el recordatorio."""
    plan = await plan_service.update_plan(session, user, plan_id, data.model_dump(exclude_unset=True))
    return await plan_service.to_plan_detail(session, plan)


@router.post("/{plan_id}/cancel", response_model=PlanDetail)
async def cancel_plan(
    plan_id: int,
    user: User = Depends(require_planner),
    session: AsyncSession = Depends(get_db),
) -> PlanDetail:
    """Queda en el historial como CANCELLED (409 si no estaba programado)."""
    plan = await plan_service.cancel_plan(session, user, plan_id)
    return await plan_service.to_plan_detail(session, plan)


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plan(
    plan_id: int,
    user: User = Depends(require_planner),
    session: AsyncSession = Depends(get_db),
) -> Response:
    await plan_service.delete_plan(session, user, plan_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{plan_id}/calendar.ics", response_class=Response)
async def download_plan_ics(
    plan_id: int,
    user: User = Depends(require_planner),
    session: AsyncSession = Depends(get_db),
) -> Response:
    """Evento para Apple Calendar, Outlook y otros (con alarma si el plan tiene recordatorio).
    El enlace de Google Calendar lo arma el frontend."""
    plan = await plan_service.get_own_plan(session, user, plan_id)
    establishment = await session.get(Establishment, plan.establishment_id)
    assert establishment is not None
    return Response(
        content=build_plan_ics(plan, establishment).encode("utf-8"),
        media_type="text/calendar; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="plan-{plan.id}.ics"',
            "Cache-Control": "no-store",
        },
    )
