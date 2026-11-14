"""Recalcula desde cero los agregados de puntuación de todos los establecimientos.

Uso (desde la carpeta PlanATi_Backend):

    python -m scripts.recompute_ratings

Sirve para corregir derivas y después de cambiar RANKING_MIN_REVIEWS o RANKING_PRIOR_MEAN
(p. ej. cuando haya volumen suficiente para usar el promedio global como valor previo).
"""

import asyncio

from app.db.session import engine, session_factory
from app.models import *  # noqa: F401,F403  (registra todos los modelos)
from app.services.rating_service import recompute_all_ratings


async def main() -> None:
    try:
        async with session_factory() as session:
            updated = await recompute_all_ratings(session)
            await session.commit()
        print(f"Agregados recalculados para {updated} establecimientos.")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
