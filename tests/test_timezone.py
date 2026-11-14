from datetime import datetime, timedelta, timezone

from app.core.time import LOCAL_TZ, UTC, ensure_utc, local_day_end, local_day_start, to_local

BOGOTA = timezone(timedelta(hours=-5))


def test_local_timezone_is_colombia() -> None:
    assert LOCAL_TZ.key == "America/Bogota"
    assert datetime(2026, 11, 20, 12, 0, tzinfo=LOCAL_TZ).utcoffset() == timedelta(hours=-5)
    # Colombia no tiene horario de verano: el offset es el mismo en junio.
    assert datetime(2026, 6, 20, 12, 0, tzinfo=LOCAL_TZ).utcoffset() == timedelta(hours=-5)


def test_ensure_utc_assumes_naive_values_are_utc() -> None:
    # SQLite devuelve las fechas sin zona; se guardaron en UTC.
    assert ensure_utc(datetime(2026, 11, 21, 0, 30)) == datetime(2026, 11, 21, 0, 30, tzinfo=UTC)
    assert ensure_utc(datetime(2026, 11, 21, 0, 30)).tzinfo is UTC


def test_evening_plan_in_colombia_is_stored_as_next_day_utc() -> None:
    local_plan = datetime(2026, 11, 20, 19, 30, tzinfo=BOGOTA)
    stored = ensure_utc(local_plan)
    assert stored == datetime(2026, 11, 21, 0, 30, tzinfo=UTC)
    assert stored.tzinfo is UTC


def test_to_local_returns_colombian_wall_time_and_weekday() -> None:
    local = to_local(datetime(2026, 11, 21, 0, 30, tzinfo=UTC))
    assert (local.year, local.month, local.day, local.hour, local.minute) == (2026, 11, 20, 19, 30)
    # El horario se valida contra el día local (viernes 20), no contra el día UTC (sábado 21).
    assert local.weekday() == 4
    # Naive se interpreta como UTC.
    assert to_local(datetime(2026, 11, 21, 0, 30)) == local


def test_local_day_start_uses_colombian_midnight() -> None:
    # 22:00 del 12 en Colombia = 03:00 UTC del 13: el día local sigue siendo el 12.
    now = datetime(2026, 11, 13, 3, 0, tzinfo=UTC)
    assert local_day_start(now) == datetime(2026, 11, 12, 5, 0, tzinfo=UTC)
    assert local_day_end(now) == datetime(2026, 11, 13, 5, 0, tzinfo=UTC)

    # 01:00 del 13 en Colombia = 06:00 UTC del 13: ya es el día local 13.
    later = datetime(2026, 11, 13, 6, 0, tzinfo=UTC)
    assert local_day_start(later) == datetime(2026, 11, 13, 5, 0, tzinfo=UTC)


def test_local_day_start_on_exact_midnight() -> None:
    midnight = datetime(2026, 11, 13, 5, 0, tzinfo=UTC)  # 00:00 en Colombia
    assert local_day_start(midnight) == midnight
    assert local_day_start(midnight - timedelta(microseconds=1)) == midnight - timedelta(days=1)
