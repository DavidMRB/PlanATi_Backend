"""Ejecuta el ciclo de recordatorios fuera de la API.

    python -m scripts.run_reminders --once   # una pasada (para cron / programador de tareas)
    python -m scripts.run_reminders          # en bucle cada REMINDER_POLL_SECONDS (Ctrl+C para salir)

Úsalo con `REMINDERS_ENABLED=false` en la API si prefieres un único ejecutor. Es idempotente:
ejecutarlo a la vez que la API no duplica recordatorios.
"""

import argparse
import asyncio

from app.db.session import engine
from app.workers.reminders import reminders_loop, run_once


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--once", action="store_true", help="Una sola pasada y salir")
    args = parser.parse_args()
    try:
        if args.once:
            result = await run_once()
            print(
                f"Recordatorios enviados: {result['reminders']}, planes completados: {result['completed']}, "
                f"notificaciones purgadas: {result['purged']}."
            )
        else:
            stop = asyncio.Event()
            try:
                await reminders_loop(stop)
            except asyncio.CancelledError:
                stop.set()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
