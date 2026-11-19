"""Utilidades de fecha y hora.

Regla del proyecto: las fechas se guardan y se comparan **siempre en UTC**. SQLite descarta el
offset al guardar, así que todo valor se normaliza con `ensure_utc` antes de persistirlo o
compararlo, y también al leerlo. La hora local (`APP_TIMEZONE`, America/Bogota) solo se usa para
validar contra horarios del establecimiento, armar textos para el usuario y calcular el "inicio
del día" de los límites diarios.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from app.core.config import settings

UTC = timezone.utc
# En Windows, zoneinfo necesita el paquete `tzdata` (está en requirements.txt).
LOCAL_TZ = ZoneInfo(settings.app_timezone)


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Una fecha sin zona se asume en UTC (así la devuelve SQLite); una con zona se convierte a UTC."""
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def to_local(value: datetime) -> datetime:
    """Convierte a la hora local de la aplicación (para validar horarios y armar textos)."""
    return ensure_utc(value).astimezone(LOCAL_TZ)


def local_day_start(value: datetime | None = None) -> datetime:
    """Inicio (00:00 hora local) del día local que contiene `value`, expresado en UTC.

    Sirve para los límites diarios: "reseñas creadas desde el inicio del día en Colombia".
    """
    local = to_local(value if value is not None else utcnow())
    start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_local.astimezone(UTC)


def local_day_end(value: datetime | None = None) -> datetime:
    """Fin exclusivo (00:00 del día siguiente, hora local) del día local que contiene `value`, en UTC."""
    start_local = to_local(local_day_start(value))
    return (start_local + timedelta(days=1)).astimezone(UTC)
