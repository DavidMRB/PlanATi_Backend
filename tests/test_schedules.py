"""Horarios editables y `is_open_at` (fase B4)."""

from dataclasses import dataclass
from datetime import datetime, time

import pytest

from app.services.schedule_service import ScheduleValidationError, is_open_at, validate_schedules
from tests.conftest import API


@dataclass
class Slot:
    day_of_week: int
    opening_time: time
    closing_time: time


def slot(day: int, opening: str, closing: str) -> Slot:
    return Slot(day, time.fromisoformat(opening), time.fromisoformat(closing))


# 2026-11-16 es lunes (weekday 0).
def at(day_offset: int, hhmm: str) -> datetime:
    hour, minute = map(int, hhmm.split(":"))
    return datetime(2026, 11, 16 + day_offset, hour, minute)


# --- is_open_at (sin base de datos) -------------------------------------------------------------


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (at(0, "07:59"), False),
        (at(0, "08:00"), True),  # la apertura se incluye
        (at(0, "14:59"), True),
        (at(0, "15:00"), False),  # el cierre se excluye
        (at(1, "10:00"), False),  # martes sin horario
    ],
)
def test_is_open_at_regular_segment_edges(moment: datetime, expected: bool) -> None:
    assert is_open_at([slot(0, "08:00", "15:00")], moment) is expected


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (at(5, "17:59"), False),
        (at(5, "18:00"), True),
        (at(5, "23:59"), True),
        (at(6, "00:00"), True),  # madrugada del domingo: sigue el tramo del sábado
        (at(6, "01:59"), True),
        (at(6, "02:00"), False),
        (at(6, "20:00"), False),
        (at(4, "01:00"), False),  # la madrugada del sábado no pertenece al tramo del sábado
    ],
)
def test_is_open_at_segment_crossing_midnight(moment: datetime, expected: bool) -> None:
    assert is_open_at([slot(5, "18:00", "02:00")], moment) is expected


def test_is_open_at_sunday_night_continues_on_monday() -> None:
    schedules = [slot(6, "20:00", "03:00")]
    assert is_open_at(schedules, at(0, "02:30")) is True
    assert is_open_at(schedules, at(0, "03:00")) is False


# --- validate_schedules -------------------------------------------------------------------------


def test_valid_schedules_with_two_segments_and_midnight() -> None:
    validate_schedules([slot(0, "08:00", "15:00"), slot(0, "18:00", "02:00"), slot(1, "08:00", "15:00")])
    # Un tramo puede empezar justo cuando termina otro.
    validate_schedules([slot(0, "08:00", "12:00"), slot(0, "12:00", "16:00")])


@pytest.mark.parametrize(
    ("items", "message"),
    [
        ([slot(0, "08:00", "08:00")], "iguales"),
        ([slot(0, "08:00", "15:00"), slot(0, "14:00", "18:00")], "solapan"),
        ([slot(0, "08:00", "15:00"), slot(0, "08:00", "15:00")], "solapan"),
        ([slot(0, "18:00", "03:00"), slot(1, "02:00", "10:00")], "solapan"),  # el nocturno invade el martes
        ([slot(6, "20:00", "03:00"), slot(0, "01:00", "09:00")], "solapan"),  # domingo → lunes
        ([slot(2, "06:00", "08:00"), slot(2, "09:00", "10:00"), slot(2, "11:00", "12:00"), slot(2, "13:00", "14:00")], "más de 3"),
    ],
)
def test_invalid_schedules(items: list[Slot], message: str) -> None:
    with pytest.raises(ScheduleValidationError, match=message):
        validate_schedules(items)


# --- API ----------------------------------------------------------------------------------------


def test_put_and_get_schedules(approved_restaurant, make_client) -> None:
    owner, establishment_id = approved_restaurant("a")
    payload = [
        {"day_of_week": 4, "opening_time": "18:00", "closing_time": "02:00"},
        {"day_of_week": 0, "opening_time": "08:00", "closing_time": "15:00"},
        {"day_of_week": 0, "opening_time": "18:00", "closing_time": "22:30"},
    ]
    response = owner.put(f"{API}/restaurant/schedules", json=payload)
    assert response.status_code == 200, response.text
    saved = [(s["day_of_week"], s["opening_time"], s["closing_time"]) for s in response.json()]
    assert saved == [(0, "08:00:00", "15:00:00"), (0, "18:00:00", "22:30:00"), (4, "18:00:00", "02:00:00")]
    assert [(s["day_of_week"], s["opening_time"]) for s in owner.get(f"{API}/restaurant/schedules").json()] == [
        (0, "08:00:00"), (0, "18:00:00"), (4, "18:00:00")
    ]
    public = make_client().get(f"{API}/establishments/{establishment_id}").json()
    assert len(public["schedules"]) == 3

    # Reemplaza todo; lista vacía = sin horarios.
    assert owner.put(f"{API}/restaurant/schedules", json=[]).json() == []
    assert owner.get(f"{API}/restaurant/schedules").json() == []


def test_put_schedules_errors(approved_restaurant, register_restaurant, user_client) -> None:
    owner, _ = approved_restaurant("a")
    original = [{"day_of_week": 0, "opening_time": "08:00", "closing_time": "15:00"}]
    assert owner.put(f"{API}/restaurant/schedules", json=original).status_code == 200

    overlapping = original + [{"day_of_week": 0, "opening_time": "14:00", "closing_time": "16:00"}]
    response = owner.put(f"{API}/restaurant/schedules", json=overlapping)
    assert response.status_code == 400
    assert "solapan" in response.json()["detail"]
    # Un PUT rechazado no borra los horarios anteriores.
    assert len(owner.get(f"{API}/restaurant/schedules").json()) == 1

    assert owner.put(f"{API}/restaurant/schedules", json=[{"day_of_week": 7, "opening_time": "08:00", "closing_time": "09:00"}]).status_code == 422
    assert owner.put(f"{API}/restaurant/schedules", json=[{"day_of_week": 0, "opening_time": "25:00", "closing_time": "09:00"}]).status_code == 422

    pending, _ = register_restaurant("p")
    assert pending.put(f"{API}/restaurant/schedules", json=original).status_code == 403
    user, _ = user_client("a")
    assert user.get(f"{API}/restaurant/schedules").status_code == 403
