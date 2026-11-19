"""Ciclo de recordatorios dentro del proceso de la API (lo arranca el `lifespan` de `app/main.py`
si `REMINDERS_ENABLED=true`). Alternativa con un solo ejecutor: `REMINDERS_ENABLED=false` y
`python -m scripts.run_reminders --once` cada minuto desde cron o el programador de tareas."""

import asyncio
import logging
from contextlib import suppress

from app.core.config import settings
from app.core.time import utcnow
from app.db.session import session_factory
from app.services.reminder_service import run_cycle

logger = logging.getLogger(__name__)


async def run_once() -> dict[str, int]:
    async with session_factory() as session:
        return await run_cycle(session, utcnow())


async def reminders_loop(stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await run_once()
        except Exception:  # noqa: BLE001 — el ciclo nunca debe morir por un fallo puntual
            logger.exception("Fallo en el ciclo de recordatorios")
        with suppress(asyncio.TimeoutError):
            await asyncio.wait_for(stop.wait(), timeout=settings.reminder_poll_seconds)
