"""Horarios de atención del establecimiento (plan de la fase 2, sección 7.4).

Los horarios están en hora local de la aplicación (`APP_TIMEZONE`, America/Bogota) y
`day_of_week` va de 0 = lunes a 6 = domingo (como `datetime.weekday()`). Si `closing_time` es
menor que `opening_time`, el tramo cruza la medianoche y termina el día siguiente.
"""

# GUIA #9 TEMA: Matrices (creación, recorrido y operaciones) -> el horario semanal es una matriz irregular: fila = día (0 a 6) y
# columna = tramo (de 0 a 3 por día). Aquí se valida, se consulta y se ordena; el frontend la arma
# en PlanATi_Frontend/components/establishment-management/schedules.ts.
from collections.abc import Iterable, Sequence
from datetime import datetime, time
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.establishment import Establishment, Schedule

MINUTES_PER_DAY = 24 * 60
MINUTES_PER_WEEK = 7 * MINUTES_PER_DAY
MAX_SEGMENTS_PER_DAY = 3
# GUIA #7 TEMA: Cadenas, listas, tuplas y diccionarios -> tupla inmutable con los días; la posición coincide con `day_of_week`.
DAY_NAMES = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


class ScheduleLike(Protocol):
    day_of_week: int
    opening_time: time
    closing_time: time


class ScheduleValidationError(ValueError):
    """Horarios inválidos (400)."""


# GUIA #10 TEMA: Subalgoritmos (funciones, procedimientos y modularización) -> funciones pequeñas con `return` que reutiliza el resto del módulo.
def to_minutes(value: time) -> int:
    return value.hour * 60 + value.minute


def _fmt(value: time) -> str:
    return value.strftime("%H:%M")


def _week_interval(item: ScheduleLike) -> tuple[int, int]:
    """[inicio, fin) en minutos desde el lunes 00:00; el fin puede pasar de la semana (domingo → lunes)."""
    start, end = to_minutes(item.opening_time), to_minutes(item.closing_time)
    if end <= start:  # cruza la medianoche
        end += MINUTES_PER_DAY
    offset = item.day_of_week * MINUTES_PER_DAY
    return offset + start, offset + end


# GUIA #6 TEMA: Ciclos -> `for` sobre una tupla de desplazamientos; el `return True` corta el ciclo en cuanto hay choque.
def _overlaps(a: tuple[int, int], b: tuple[int, int]) -> bool:
    # La semana es circular: un tramo del domingo que cruza la medianoche continúa el lunes.
    for shift in (-MINUTES_PER_WEEK, 0, MINUTES_PER_WEEK):
        if a[0] < b[1] + shift and b[0] + shift < a[1]:
            return True
    return False


def _describe(item: ScheduleLike) -> str:
    return f"{DAY_NAMES[item.day_of_week]} {_fmt(item.opening_time)}–{_fmt(item.closing_time)}"


# GUIA #10 TEMA: Subalgoritmos (funciones, procedimientos y modularización) -> procedimiento (`-> None`): no devuelve nada; lanza ScheduleValidationError (400).
def validate_schedules(items: Sequence[ScheduleLike]) -> None:
    """Lanza `ScheduleValidationError` si un tramo no tiene duración, si hay más de 3 tramos en un día
    o si dos tramos se solapan (incluido un tramo nocturno que invade la mañana del día siguiente)."""
    # GUIA #9 TEMA: Matrices (creación, recorrido y operaciones) -> operación por fila: cuenta los tramos de cada día con un diccionario (máx. 3).
    # GUIA #6 TEMA: Ciclos -> `for` recorre cada tramo y valida día, formato y duración.
    per_day: dict[int, int] = {}
    for item in items:
        if not 0 <= item.day_of_week <= 6:
            raise ScheduleValidationError("El día debe ir de 0 (lunes) a 6 (domingo).")
        if item.opening_time.second or item.closing_time.second:
            raise ScheduleValidationError("Las horas se indican en horas y minutos (HH:MM).")
        if item.opening_time == item.closing_time:
            raise ScheduleValidationError(
                f"El horario del {_describe(item)} no es válido: la apertura y el cierre no pueden ser iguales."
            )
        per_day[item.day_of_week] = per_day.get(item.day_of_week, 0) + 1
        if per_day[item.day_of_week] > MAX_SEGMENTS_PER_DAY:
            raise ScheduleValidationError(
                f"El {DAY_NAMES[item.day_of_week]} tiene más de {MAX_SEGMENTS_PER_DAY} tramos de horario."
            )

    # GUIA #9 TEMA: Matrices (creación, recorrido y operaciones) -> recorrido con ciclos anidados: compara cada tramo con todos los siguientes para
    # detectar solapamientos (incluido un tramo nocturno que invade la madrugada del día siguiente).
    intervals = [(item, _week_interval(item)) for item in items]
    for index, (item, interval) in enumerate(intervals):
        for other, other_interval in intervals[index + 1 :]:
            if _overlaps(interval, other_interval):
                raise ScheduleValidationError(
                    f"Los horarios se solapan: {_describe(item)} y {_describe(other)}."
                )


# GUIA #10 TEMA: Subalgoritmos (funciones, procedimientos y modularización) -> función booleana con `return`: ¿está abierto el local a esa hora?
# GUIA #9 TEMA: Matrices (creación, recorrido y operaciones) -> integración: consulta los tramos de hoy y los de ayer que cruzan la medianoche.
def is_open_at(schedules: Iterable[ScheduleLike], local_dt: datetime) -> bool:
    """¿Está abierto a esa hora local? La apertura se incluye y el cierre se excluye.

    Un tramo que cruza la medianoche (p. ej. sábado 18:00–02:00) cubre también la madrugada del
    día siguiente (domingo hasta las 01:59).
    """
    minute = local_dt.hour * 60 + local_dt.minute
    today, yesterday = local_dt.weekday(), (local_dt.weekday() - 1) % 7  # weekday(): 0 = lunes
    for s in schedules:
        start, end = to_minutes(s.opening_time), to_minutes(s.closing_time)
        if start < end and s.day_of_week == today and start <= minute < end:
            return True
        if start > end:  # cruza medianoche
            if s.day_of_week == today and minute >= start:
                return True
            if s.day_of_week == yesterday and minute < end:
                return True
    return False


# GUIA #8 TEMA: Vectores (ordenamiento y búsqueda) -> `sorted()` crea una lista nueva ordenada por día y hora de apertura;
# la `lambda` devuelve una tupla como criterio de orden.
def sorted_schedules(schedules: Iterable[Schedule]) -> list[Schedule]:
    return sorted(schedules, key=lambda s: (s.day_of_week, s.opening_time, s.id or 0))


# Registro del horario: valida y reemplaza toda la matriz semanal del establecimiento.
async def replace_schedules(
    session: AsyncSession, establishment: Establishment, items: Sequence[ScheduleLike]
) -> list[Schedule]:
    """Valida y reemplaza todos los horarios del establecimiento (commit incluido)."""
    validate_schedules(items)
    establishment.schedules = [
        Schedule(day_of_week=item.day_of_week, opening_time=item.opening_time, closing_time=item.closing_time)
        for item in items
    ]
    await session.commit()
    await session.refresh(establishment, attribute_names=["schedules"])
    return sorted_schedules(establishment.schedules)
