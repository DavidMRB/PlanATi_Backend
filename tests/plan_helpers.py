"""Utilidades compartidas por las pruebas de planes (B6)."""

from datetime import datetime, time, timedelta

from app.core.time import LOCAL_TZ, utcnow
from tests.conftest import API


def next_local(weekday: int, hour: int, minute: int = 0, *, min_days: int = 2) -> datetime:
    """Próxima fecha (hora de Colombia) con ese día de la semana (0 = lunes), al menos `min_days` después de hoy."""
    day = utcnow().astimezone(LOCAL_TZ).date() + timedelta(days=min_days)
    while day.weekday() != weekday:
        day += timedelta(days=1)
    return datetime.combine(day, time(hour, minute), tzinfo=LOCAL_TZ)


def in_days(days: int, hour: int = 12) -> datetime:
    day = utcnow().astimezone(LOCAL_TZ).date() + timedelta(days=days)
    return datetime.combine(day, time(hour, 0), tzinfo=LOCAL_TZ)


def iso(value: datetime) -> str:
    return value.isoformat()


def add_product(owner_client, name: str = "Picada", price: str = "25000", **extra) -> int:
    response = owner_client.post(f"{API}/restaurant/products", json={"name": name, "price": price, **extra})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def put_schedules(owner_client, schedules: list[tuple[int, str, str]]) -> None:
    body = [{"day_of_week": d, "opening_time": o, "closing_time": c} for d, o, c in schedules]
    response = owner_client.put(f"{API}/restaurant/schedules", json=body)
    assert response.status_code == 200, response.text


def create_plan(client, establishment_id: int, scheduled_at: datetime | None = None, expected: int = 201, **body):
    body.setdefault("establishment_id", establishment_id)
    body.setdefault("scheduled_at", iso(scheduled_at or in_days(3)))
    response = client.post(f"{API}/plans", json=body)
    assert response.status_code == expected, response.text
    return response.json()
