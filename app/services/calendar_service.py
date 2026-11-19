"""Exporta un plan como evento de calendario (`.ics`, RFC 5545) sin dependencias externas.

- Fin de línea CRLF, líneas plegadas a 75 octetos (sin partir caracteres UTF-8) y escape de
  `\\`, `;`, `,` y saltos de línea en los textos.
- Fechas en UTC (`...Z`). `UID` estable (`plan-{id}@planati`): al descargarlo de nuevo tras editar el
  plan, los calendarios que lo soportan actualizan el evento en lugar de duplicarlo.
- `VALARM` solo si el plan tiene recordatorio, para que también avise el calendario del teléfono.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from app.core.config import settings
from app.core.time import ensure_utc, utcnow
from app.models.establishment import Establishment
from app.models.plan import Plan

CRLF = "\r\n"
MAX_LINE_OCTETS = 75


def escape_text(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
        .replace("\r", "\\n")
    )


def fold_line(line: str) -> str:
    """Pliega a 75 octetos: las líneas de continuación empiezan con un espacio."""
    chunks: list[str] = []
    current = ""
    limit = MAX_LINE_OCTETS
    for char in line:
        if len((current + char).encode("utf-8")) > limit:
            chunks.append(current)
            current = char
            limit = MAX_LINE_OCTETS - 1  # el espacio inicial cuenta
        else:
            current += char
    chunks.append(current)
    return (CRLF + " ").join(chunks)


def format_utc(value: datetime) -> str:
    return ensure_utc(value).strftime("%Y%m%dT%H%M%SZ")


def format_cop(amount: Decimal) -> str:
    """$ 54.000 (sin decimales si son cero), como se escribe en Colombia."""
    amount = Decimal(amount).quantize(Decimal("0.01"))
    integer, cents = divmod(amount, 1)
    text = f"{int(integer):,}".replace(",", ".")
    if cents:
        text += "," + f"{cents:.2f}"[2:]
    return f"$ {text}"


def plan_url(plan_id: int) -> str:
    return f"{settings.frontend_url.rstrip('/')}/plans/{plan_id}"


def _description(plan: Plan) -> str:
    people = "persona" if plan.party_size == 1 else "personas"
    lines = [f"{plan.party_size} {people}."]
    if plan.items:
        lines.append("Platos:")
        lines += [f"- {item.quantity} × {item.name_snapshot}" for item in plan.items]
        lines.append(f"Total estimado: {format_cop(plan.total_amount)} {plan.currency}")
    if plan.notes:
        lines.append(f"Notas: {plan.notes}")
    lines.append(f"Ver el plan: {plan_url(plan.id)}")
    return "\n".join(lines)


def build_plan_ics(plan: Plan, establishment: Establishment, *, now: datetime | None = None) -> str:
    start = ensure_utc(plan.scheduled_at)
    end = start + timedelta(minutes=settings.plan_default_duration_minutes)
    title = plan.title or f"Plan en {establishment.name}"
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//PlanATi//Planes//ES",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:plan-{plan.id}@planati",
        f"DTSTAMP:{format_utc(now or utcnow())}",
        f"DTSTART:{format_utc(start)}",
        f"DTEND:{format_utc(end)}",
        f"SUMMARY:{escape_text(title)}",
        f"LOCATION:{escape_text(f'{establishment.name}, {establishment.address}')}",
    ]
    if establishment.latitude is not None and establishment.longitude is not None:
        lines.append(f"GEO:{Decimal(establishment.latitude):f};{Decimal(establishment.longitude):f}")
    lines += [
        f"DESCRIPTION:{escape_text(_description(plan))}",
        f"URL:{plan_url(plan.id)}",
        f"STATUS:{'CANCELLED' if plan.status == 'CANCELLED' else 'CONFIRMED'}",
    ]
    if plan.reminder_minutes_before is not None and plan.status != "CANCELLED":
        lines += [
            "BEGIN:VALARM",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{escape_text(title)}",
            f"TRIGGER:-PT{plan.reminder_minutes_before}M",
            "END:VALARM",
        ]
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return CRLF.join(fold_line(line) for line in lines) + CRLF
