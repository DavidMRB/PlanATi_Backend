"""Planes (agendamiento de visitas) del usuario (plan de la fase 2, sección 7.7).

Reglas principales:
- Solo cuentas `user` activas con teléfono verificado; todo se filtra por `user_id` (ajeno → 404).
- `scheduled_at` se guarda en UTC (redondeado al minuto) y se valida en hora de Colombia contra los
  horarios del local (`schedule_service.is_open_at`), si los tiene.
- El total se calcula en el servidor con los precios ACTUALES del catálogo y se congela con cada
  ítem (`name_snapshot`, `unit_price_snapshot`).
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.time import ensure_utc, to_local, utcnow
from app.models.establishment import Establishment, MenuItem
from app.models.plan import Plan, PlanItem
from app.models.user import User
from app.schemas.plan import (
    PlanDetail,
    PlanEstablishment,
    PlanItemInput,
    PlanItemResponse,
    PlanListItem,
)
from app.services.schedule_service import is_open_at

MAX_RANGE_DAYS = 92
CLOSED_MESSAGE = "El establecimiento está cerrado en ese horario."
REMINDER_IN_PAST_MESSAGE = "El recordatorio quedaría en el pasado; elige uno más corto."


# --- Errores de dominio (app/main.py los convierte en {"detail", ...extra}) ---------------------


class PlanError(Exception):
    status_code = 400

    def __init__(self, detail: str, **extra: Any) -> None:
        self.detail = detail
        self.extra = extra
        super().__init__(detail)


class PlanNotFoundError(PlanError):
    status_code = 404


class PlanForbiddenError(PlanError):
    status_code = 403


class PlanConflictError(PlanError):
    status_code = 409


class PlanLimitError(PlanError):
    status_code = 429


# --- Quién puede planear ------------------------------------------------------------------------


def check_planner(user: User) -> None:
    if user.role != "user":
        raise PlanForbiddenError("Solo las cuentas de usuario pueden crear planes.", code="ROLE_NOT_ALLOWED")
    if not user.phone_verified or user.status != "ACTIVE":
        raise PlanForbiddenError(
            "Debes completar la verificación telefónica para crear planes.", code="PHONE_NOT_VERIFIED"
        )


# --- Validaciones ---------------------------------------------------------------------------------


def normalize_scheduled_at(value: datetime) -> datetime:
    """UTC y redondeado al minuto (los horarios del local tienen precisión de minutos)."""
    return ensure_utc(value).replace(second=0, microsecond=0)


def _check_window(scheduled_at: datetime, now: datetime) -> None:
    if scheduled_at < now + timedelta(minutes=settings.plan_min_lead_minutes):
        raise PlanError(
            f"El plan debe programarse con al menos {settings.plan_min_lead_minutes} minutos de anticipación."
        )
    if scheduled_at > now + timedelta(days=settings.plan_max_days_ahead):
        raise PlanError(f"El plan no puede programarse a más de {settings.plan_max_days_ahead} días.")


def _check_open(establishment: Establishment, scheduled_at: datetime) -> None:
    # Un local sin horarios publicados no restringe la hora.
    if establishment.schedules and not is_open_at(establishment.schedules, to_local(scheduled_at)):
        raise PlanError(CLOSED_MESSAGE, code="CLOSED")


def _reminder_at(scheduled_at: datetime, minutes: int | None, now: datetime) -> datetime | None:
    if minutes is None:
        return None
    reminder_at = scheduled_at - timedelta(minutes=minutes)
    if reminder_at <= now:
        raise PlanError(REMINDER_IN_PAST_MESSAGE, code="REMINDER_IN_PAST")
    return reminder_at


async def _approved_establishment(session: AsyncSession, establishment_id: int) -> Establishment:
    establishment = await session.get(Establishment, establishment_id)
    if establishment is None or establishment.status != "APPROVED":
        raise PlanNotFoundError("Establecimiento no encontrado")
    return establishment


# GUIA 5 TEMA: Calcular un valor y generar resultado -> devuelve los ítems y el total según precio y cantidad.
# GUIA 2 TEMA: Alternativa a float para dinero -> Decimal conserva la precisión decimal de los precios.
async def _build_items(
    session: AsyncSession, establishment: Establishment, items: Sequence[PlanItemInput]
) -> tuple[list[PlanItem], Decimal]:
    """Ítems con nombre y precio actuales congelados, y el total. Ajenos o no disponibles → 400."""
    if not items:
        return [], Decimal("0")
    ids = [item.menu_item_id for item in items]
    rows = await session.scalars(
        select(MenuItem).where(
            MenuItem.id.in_(ids), MenuItem.establishment_id == establishment.id, MenuItem.is_available.is_(True)
        )
    )
    # GUIA #7 TEMA: Cadenas, listas, tuplas y diccionarios -> diccionario {id: plato} para consultar cada ítem sin recorrer la lista.
    # GUIA #8 TEMA: Vectores (ordenamiento y búsqueda) -> búsqueda: `invalid` reúne los ids pedidos que no están en el catálogo.
    catalog = {menu_item.id: menu_item for menu_item in rows.all()}
    invalid = [item_id for item_id in ids if item_id not in catalog]
    if invalid:
        raise PlanError(
            "Algunos platos no existen, no son de este establecimiento o no están disponibles.",
            code="INVALID_ITEMS",
            invalid_item_ids=invalid,
        )
    built = [
        PlanItem(
            menu_item_id=item.menu_item_id,
            name_snapshot=catalog[item.menu_item_id].name,
            unit_price_snapshot=Decimal(catalog[item.menu_item_id].price),
            quantity=item.quantity,
            notes=item.notes,
        )
        for item in items
    ]
    # GUIA #9 TEMA: Matrices (creación, recorrido y operaciones) -> operación: total del plan = suma de precio x cantidad de cada ítem.
    total = sum((row.unit_price_snapshot * row.quantity for row in built), Decimal("0"))
    return built, total.quantize(Decimal("0.01"))


async def count_active_plans(session: AsyncSession, user_id: int, now: datetime) -> int:
    count = await session.scalar(
        select(func.count(Plan.id)).where(
            Plan.user_id == user_id, Plan.status == "SCHEDULED", Plan.scheduled_at >= now
        )
    )
    return int(count or 0)


def default_title(establishment_name: str) -> str:
    title = f"Plan en {establishment_name}"
    return title if len(title) <= 120 else title[:119].rstrip() + "…"


# --- Crear, editar, cancelar, eliminar -------------------------------------------------------------


async def create_plan(session: AsyncSession, user: User, data: Any, *, now: datetime | None = None) -> Plan:
    """`data` es un `PlanCreate`."""
    now = ensure_utc(now or utcnow())
    check_planner(user)
    scheduled_at = normalize_scheduled_at(data.scheduled_at)
    _check_window(scheduled_at, now)
    establishment = await _approved_establishment(session, data.establishment_id)
    _check_open(establishment, scheduled_at)
    reminder_at = _reminder_at(scheduled_at, data.reminder_minutes_before, now)
    items, total = await _build_items(session, establishment, data.items)
    if await count_active_plans(session, user.id, now) >= settings.plan_max_active:
        raise PlanLimitError(
            f"Tienes {settings.plan_max_active} planes programados. Cancela o elimina alguno para crear otro."
        )
    plan = Plan(
        user_id=user.id,
        establishment_id=establishment.id,
        title=data.title or default_title(establishment.name),
        scheduled_at=scheduled_at,
        party_size=data.party_size,
        notes=data.notes,
        reminder_minutes_before=data.reminder_minutes_before,
        reminder_at=reminder_at,
        total_amount=total,
        items=items,
    )
    session.add(plan)
    await session.commit()
    return await get_own_plan(session, user, plan.id)


async def get_own_plan(session: AsyncSession, user: User, plan_id: int) -> Plan:
    plan = await session.scalar(
        select(Plan).where(Plan.id == plan_id, Plan.user_id == user.id).execution_options(populate_existing=True)
    )
    if plan is None:
        raise PlanNotFoundError("Plan no encontrado")
    return plan


def _ensure_editable(plan: Plan, now: datetime) -> None:
    if plan.status != "SCHEDULED" or ensure_utc(plan.scheduled_at) <= now:
        raise PlanConflictError("Solo se pueden modificar planes programados que aún no han pasado.")


async def update_plan(
    session: AsyncSession, user: User, plan_id: int, changes: dict[str, Any], *, now: datetime | None = None
) -> Plan:
    """`changes` = `PlanUpdate.model_dump(exclude_unset=True)` (con `items` como `PlanItemInput`)."""
    now = ensure_utc(now or utcnow())
    plan = await get_own_plan(session, user, plan_id)
    _ensure_editable(plan, now)
    establishment = await session.get(Establishment, plan.establishment_id)
    if establishment is None or establishment.status != "APPROVED":
        raise PlanError(
            "El establecimiento ya no está disponible; puedes cancelar o eliminar el plan.",
            code="ESTABLISHMENT_UNAVAILABLE",
        )

    scheduled_at = ensure_utc(plan.scheduled_at)
    # GUIA 3 TEMA: Condiciones anidadas -> si llega la fecha, valida ventana y horario solo cuando cambia.
    if "scheduled_at" in changes:
        scheduled_at = normalize_scheduled_at(changes["scheduled_at"])
        if scheduled_at != ensure_utc(plan.scheduled_at):
            _check_window(scheduled_at, now)
            _check_open(establishment, scheduled_at)
    minutes = changes.get("reminder_minutes_before", plan.reminder_minutes_before)
    timing_changed = scheduled_at != ensure_utc(plan.scheduled_at) or minutes != plan.reminder_minutes_before
    if timing_changed:
        plan.reminder_at = _reminder_at(scheduled_at, minutes, now)
        plan.reminder_sent_at = None
        plan.scheduled_at = scheduled_at
        plan.reminder_minutes_before = minutes

    if "items" in changes:
        items = [PlanItemInput.model_validate(item) for item in changes["items"]]
        new_items, total = await _build_items(session, establishment, items)
        plan.items.clear()
        await session.flush()
        plan.items.extend(new_items)
        plan.total_amount = total
    if "party_size" in changes:
        plan.party_size = changes["party_size"]
    if "title" in changes:
        plan.title = changes["title"] or default_title(establishment.name)
    if "notes" in changes:
        plan.notes = changes["notes"]
    plan.updated_at = now
    await session.commit()
    return await get_own_plan(session, user, plan.id)


# GUIA 5 TEMA: Realizar una operación -> comprueba el plan y confirma su cancelación.
async def cancel_plan(session: AsyncSession, user: User, plan_id: int, *, now: datetime | None = None) -> Plan:
    now = ensure_utc(now or utcnow())
    plan = await get_own_plan(session, user, plan_id)
    if plan.status != "SCHEDULED":
        raise PlanConflictError("Solo se puede cancelar un plan programado.")
    plan.status = "CANCELLED"
    plan.updated_at = now
    await session.commit()
    return await get_own_plan(session, user, plan.id)


async def delete_plan(session: AsyncSession, user: User, plan_id: int) -> None:
    plan = await get_own_plan(session, user, plan_id)
    await session.delete(plan)
    await session.commit()


# --- Consultas ------------------------------------------------------------------------------------


async def list_plans(
    session: AsyncSession,
    user: User,
    *,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    status: str | None = None,
    skip: int = 0,
    limit: int = 20,
    now: datetime | None = None,
) -> tuple[list[Plan], int]:
    """Con `from`/`to`: planes en ese rango (máx. 92 días). Sin ellos: los próximos. Orden ascendente."""
    now = ensure_utc(now or utcnow())
    conditions: list[Any] = [Plan.user_id == user.id]
    if (date_from is None) != (date_to is None):
        raise PlanError("Envía `from` y `to` juntos.")
    if date_from is not None and date_to is not None:
        start, end = ensure_utc(date_from), ensure_utc(date_to)
        if end <= start:
            raise PlanError("`to` debe ser posterior a `from`.")
        if end - start > timedelta(days=MAX_RANGE_DAYS):
            raise PlanError(f"El rango de fechas no puede superar {MAX_RANGE_DAYS} días.")
        conditions += [Plan.scheduled_at >= start, Plan.scheduled_at < end]
    else:
        conditions.append(Plan.scheduled_at >= now)
    if status:
        conditions.append(Plan.status == status)
    total = await session.scalar(select(func.count(Plan.id)).where(*conditions))
    rows = await session.scalars(
        select(Plan).where(*conditions).order_by(Plan.scheduled_at.asc(), Plan.id.asc()).offset(skip).limit(limit)
    )
    return list(rows.all()), int(total or 0)


# --- Conversión a esquemas ------------------------------------------------------------------------


def _establishment_summary(establishment: Establishment) -> PlanEstablishment:
    return PlanEstablishment(
        id=establishment.id,
        name=establishment.name,
        address=establishment.address,
        latitude=establishment.latitude,
        longitude=establishment.longitude,
        profile_image_url=establishment.profile_image_url,
    )


def _list_fields(plan: Plan, establishment: PlanEstablishment) -> dict[str, Any]:
    return {
        "id": plan.id,
        "title": plan.title or default_title(establishment.name),
        "scheduled_at": ensure_utc(plan.scheduled_at),
        "party_size": plan.party_size,
        "status": plan.status,
        "reminder_minutes_before": plan.reminder_minutes_before,
        "reminder_at": ensure_utc(plan.reminder_at) if plan.reminder_at else None,
        "total_amount": Decimal(plan.total_amount),
        "currency": plan.currency,
        "items_count": len(plan.items),
        "establishment": establishment,
        "created_at": ensure_utc(plan.created_at),
        "updated_at": ensure_utc(plan.updated_at),
    }


async def to_plan_list_items(session: AsyncSession, plans: list[Plan]) -> list[PlanListItem]:
    ids = {plan.establishment_id for plan in plans}
    summaries: dict[int, PlanEstablishment] = {}
    if ids:
        rows = await session.execute(
            select(
                Establishment.id,
                Establishment.name,
                Establishment.address,
                Establishment.latitude,
                Establishment.longitude,
                Establishment.profile_image_url,
            ).where(Establishment.id.in_(ids))
        )
        summaries = {row.id: PlanEstablishment(**row._mapping) for row in rows.all()}
    return [PlanListItem(**_list_fields(plan, summaries[plan.establishment_id])) for plan in plans]


async def to_plan_detail(session: AsyncSession, plan: Plan) -> PlanDetail:
    establishment = await session.get(Establishment, plan.establishment_id)
    assert establishment is not None
    menu_ids = [item.menu_item_id for item in plan.items if item.menu_item_id is not None]
    current: dict[int, MenuItem] = {}
    if menu_ids:
        rows = await session.scalars(
            select(MenuItem).where(MenuItem.id.in_(menu_ids), MenuItem.establishment_id == establishment.id)
        )
        current = {menu_item.id: menu_item for menu_item in rows.all()}
    items = []
    for item in plan.items:
        menu_item = current.get(item.menu_item_id) if item.menu_item_id is not None else None
        price = Decimal(menu_item.price) if menu_item is not None and menu_item.is_available else None
        unit_price = Decimal(item.unit_price_snapshot)
        items.append(
            PlanItemResponse(
                id=item.id,
                menu_item_id=item.menu_item_id if menu_item is not None else None,
                name=item.name_snapshot,
                unit_price=unit_price,
                quantity=item.quantity,
                subtotal=(unit_price * item.quantity).quantize(Decimal("0.01")),
                notes=item.notes,
                current_price=price,
                price_changed=price is None or price != unit_price,
            )
        )
    scheduled_at = ensure_utc(plan.scheduled_at)
    return PlanDetail(
        **_list_fields(plan, _establishment_summary(establishment)),
        notes=plan.notes,
        reminder_sent_at=ensure_utc(plan.reminder_sent_at) if plan.reminder_sent_at else None,
        items=items,
        establishment_available=establishment.status == "APPROVED",
        # GUIA #9 TEMA: Matrices (creación, recorrido y operaciones) -> integración: avisa si el plan queda fuera del horario del local (is_open_at).
        outside_schedule=bool(establishment.schedules) and not is_open_at(establishment.schedules, to_local(scheduled_at)),
        prices_changed=any(item.price_changed for item in items),
    )


async def future_scheduled_user_ids(session: AsyncSession, establishment_id: int, now: datetime) -> list[int]:
    """Usuarios con planes futuros SCHEDULED en un local (para avisarles si se suspende)."""
    rows = await session.scalars(
        select(Plan.user_id)
        .where(Plan.establishment_id == establishment_id, Plan.status == "SCHEDULED", Plan.scheduled_at >= now)
        .distinct()
    )
    return list(rows.all())
