"""B6: exportación del plan a `.ics` (RFC 5545)."""

from datetime import timedelta

from app.core.time import UTC
from app.services.calendar_service import escape_text, fold_line, format_cop
from tests.conftest import API
from tests.plan_helpers import add_product, create_plan, next_local


def _unfold(text: str) -> list[str]:
    return text.replace("\r\n ", "").split("\r\n")


def test_ics_download(approved_restaurant, user_client) -> None:
    owner, establishment_id = approved_restaurant("a", address="Av. 0 # 11-50; Caobos, Cúcuta")
    product = add_product(owner, "Picada, mixta", "25000")
    client, _ = user_client("u")
    scheduled = next_local(4, 19, 30)
    plan = create_plan(
        client,
        establishment_id,
        scheduled,
        title="Cumpleaños de Ana",
        notes="Mesa en terraza\nsi es posible",
        party_size=4,
        reminder_minutes_before=120,
        items=[{"menu_item_id": product, "quantity": 2}],
    )

    response = client.get(f"{API}/plans/{plan['id']}/calendar.ics")
    assert response.status_code == 200
    assert response.headers["content-type"] == "text/calendar; charset=utf-8"
    assert response.headers["content-disposition"] == f'attachment; filename="plan-{plan["id"]}.ics"'
    text = response.content.decode("utf-8")
    assert text.endswith("\r\n") and "\n" not in text.replace("\r\n", "")
    for raw in text.split("\r\n"):
        assert len(raw.encode("utf-8")) <= 75

    lines = _unfold(text)
    start = scheduled.astimezone(UTC)
    assert lines[0] == "BEGIN:VCALENDAR" and lines[-2] == "END:VCALENDAR"
    assert f"UID:plan-{plan['id']}@planati" in lines
    assert f"DTSTART:{start:%Y%m%dT%H%M%S}Z" in lines
    assert f"DTEND:{start + timedelta(hours=2):%Y%m%dT%H%M%S}Z" in lines
    assert "SUMMARY:Cumpleaños de Ana" in lines
    assert "LOCATION:Parrilla A\\, Av. 0 # 11-50\\; Caobos\\, Cúcuta" in lines
    assert any(line.startswith("GEO:7.889100;-72.496700") for line in lines)
    [description] = [line for line in lines if line.startswith("DESCRIPTION:4 personas")]
    assert "2 × Picada\\, mixta" in description and "$ 50.000 COP" in description
    assert "Mesa en terraza\\nsi es posible" in description
    assert f"/plans/{plan['id']}" in description
    assert "STATUS:CONFIRMED" in lines
    assert "BEGIN:VALARM" in lines and "TRIGGER:-PT120M" in lines


def test_ics_end_time_and_without_reminder(approved_restaurant, user_client) -> None:
    _, establishment_id = approved_restaurant("a")
    client, _ = user_client("u")
    scheduled = next_local(2, 12, 0)
    plan = create_plan(client, establishment_id, scheduled)
    lines = _unfold(client.get(f"{API}/plans/{plan['id']}/calendar.ics").text)
    start = scheduled.astimezone(UTC)
    assert f"DTSTART:{start:%Y%m%dT%H%M%S}Z" in lines
    assert f"DTEND:{start + timedelta(minutes=120):%Y%m%dT%H%M%S}Z" in lines  # PLAN_DEFAULT_DURATION_MINUTES
    assert "BEGIN:VALARM" not in lines
    assert "SUMMARY:Plan en Parrilla A" in lines


def test_cancelled_plan_ics(approved_restaurant, user_client) -> None:
    _, establishment_id = approved_restaurant("a")
    client, _ = user_client("u")
    plan = create_plan(client, establishment_id, reminder_minutes_before=60)
    client.post(f"{API}/plans/{plan['id']}/cancel")
    lines = _unfold(client.get(f"{API}/plans/{plan['id']}/calendar.ics").text)
    assert "STATUS:CANCELLED" in lines and "BEGIN:VALARM" not in lines


def test_text_helpers() -> None:
    assert escape_text("a\\b;c,d\ne") == "a\\\\b\\;c\\,d\\ne"
    folded = fold_line("DESCRIPTION:" + "ñ" * 80)
    parts = folded.split("\r\n")
    assert all(len(part.encode("utf-8")) <= 75 for part in parts)
    assert all(part.startswith(" ") for part in parts[1:])
    assert "".join(part[1:] if i else part for i, part in enumerate(parts)) == "DESCRIPTION:" + "ñ" * 80
    assert format_cop(54000) == "$ 54.000"
    assert format_cop(1234567.5) == "$ 1.234.567,50"
