"""Puntuación y posicionamiento de establecimientos (plan de la fase 2, sección 8).

Los agregados (`rating_count`, `rating_sum`, `rating_avg`, `ranking_score`) se guardan en
`establishments` y se **recalculan** con una consulta COUNT/SUM —en vez de sumar y restar— en la
misma transacción de cada cambio de reseña. `recalculate_establishment_rating` no hace commit.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import lazyload

from app.core.config import settings
from app.models.establishment import Establishment
from app.models.review import Review


# GUIA #10 TEMA: Subalgoritmos (funciones, procedimientos y modularización) -> función con parámetros opcionales y `return`: puntuación bayesiana del local.
def bayesian_score(rating_sum: int | float, rating_count: int, *, min_reviews: int | None = None, prior_mean: float | None = None) -> float:
    """ranking_score = (rating_sum + m·C) / (rating_count + m).

    m (`RANKING_MIN_REVIEWS`) es cuántas reseñas "pesa" el valor previo y C (`RANKING_PRIOR_MEAN`)
    la puntuación supuesta de un local sin reseñas. Así un local con una sola reseña de 5★ no
    supera a uno con 40 reseñas de 4,6★, y uno nuevo no queda por debajo de uno mal calificado.
    """
    m = settings.ranking_min_reviews if min_reviews is None else min_reviews
    c = settings.ranking_prior_mean if prior_mean is None else prior_mean
    if rating_count + m <= 0:
        return round(float(c), 4)
    return round((rating_sum + m * c) / (rating_count + m), 4)


# GUIA #10 TEMA: Subalgoritmos (funciones, procedimientos y modularización) -> función que llama a otra (`bayesian_score`); se usa dentro de una `lambda` en
# establishment_service.list_nearby_establishments. Lee `settings`, un global de solo lectura.
def relevance_score(ranking_score: float | None, distance_km: float, radius_km: float, *, weight: float | None = None) -> float:
    """Orden `relevance` de `/nearby`: w·(ranking_score − 1)/4 + (1 − w)·(1 − min(distancia/radio, 1))."""
    w = settings.relevance_rating_weight if weight is None else weight
    score = bayesian_score(0, 0) if ranking_score is None else ranking_score
    closeness = 1 - min(distance_km / radius_km, 1) if radius_km > 0 else 0
    return w * (score - 1) / 4 + (1 - w) * closeness


# GUIA #10 TEMA: Subalgoritmos (funciones, procedimientos y modularización) -> en vez de recorrer las reseñas con `total +=`, se usan COUNT y SUM en SQL
# y luego el procedimiento `apply_aggregates`.
# GUIA #9 TEMA: Matrices (creación, recorrido y operaciones) -> operaciones: suma y conteo para el promedio de estrellas.
async def recalculate_establishment_rating(session: AsyncSession, establishment_id: int) -> None:
    """Recalcula los agregados del establecimiento SIN hacer commit.

    Solo cuentan las reseñas VISIBLE: ocultar o restaurar una reseña cambia el promedio, pero bloquear
    su comentario no (las estrellas siguen siendo legítimas).
    """
    count, total = (
        await session.execute(
            select(func.count(Review.id), func.coalesce(func.sum(Review.rating), 0)).where(
                Review.establishment_id == establishment_id, Review.status == "VISIBLE"
            )
        )
    ).one()
    establishment = await session.get(Establishment, establishment_id, options=[lazyload("*")])
    if establishment is None:
        return
    apply_aggregates(establishment, int(count), int(total))


# GUIA #10 TEMA: Subalgoritmos (funciones, procedimientos y modularización) -> procedimiento (`-> None`) con argumento mutable: modifica el establecimiento
# recibido (conteo, suma, promedio y ranking) y el cambio persiste fuera de la función.
def apply_aggregates(establishment: Establishment, count: int, total: int) -> None:
    establishment.rating_count = count
    establishment.rating_sum = total
    establishment.rating_avg = round(total / count, 2) if count else None
    establishment.ranking_score = bayesian_score(total, count)


# GUIA #9 TEMA: Matrices (creación, recorrido y operaciones) -> totales por grupo con `GROUP BY` en SQL en lugar de recorrer [i][j] en Python.
# GUIA #7 TEMA: Cadenas, listas, tuplas y diccionarios -> diccionario {id_establecimiento: (conteo, suma)}.
async def recompute_all_ratings(session: AsyncSession) -> int:
    """Recalcula todos los establecimientos desde cero (sin commit). Devuelve cuántos actualizó."""
    totals = dict(
        (establishment_id, (int(count), int(total)))
        for establishment_id, count, total in (
            await session.execute(
                select(Review.establishment_id, func.count(Review.id), func.sum(Review.rating))
                .where(Review.status == "VISIBLE")
                .group_by(Review.establishment_id)
            )
        ).all()
    )
    # lazyload('*'): solo hacen falta las columnas, no el menú ni las reseñas de cada local.
    establishments = (await session.scalars(select(Establishment).options(lazyload("*")))).all()
    # GUIA #6 TEMA: Ciclos -> `for` aplica los agregados a cada establecimiento.
    for establishment in establishments:
        count, total = totals.get(establishment.id, (0, 0))
        apply_aggregates(establishment, count, total)
    return len(establishments)


async def rating_distribution(session: AsyncSession, establishment_id: int) -> dict[str, int]:
    """Cuántas reseñas VISIBLE hay de 1, 2, 3, 4 y 5 estrellas: {"1": n, …, "5": n}."""
    rows = dict(
        (
            await session.execute(
                select(Review.rating, func.count(Review.id))
                .where(Review.establishment_id == establishment_id, Review.status == "VISIBLE")
                .group_by(Review.rating)
            )
        ).all()
    )
    # GUIA #8 TEMA: Vectores (ordenamiento y búsqueda) -> vector de 5 posiciones creado con `range()`; `zip()` lo empareja con las estrellas.
    # GUIA #7 TEMA: Cadenas, listas, tuplas y diccionarios -> la respuesta es un diccionario {"1": n, ..., "5": n}.
    # Vector de conteos: la posición i guarda las reseñas de i + 1 estrellas (con ceros si no hay).
    counts = [int(rows.get(stars, 0)) for stars in range(1, 6)]
    return {str(stars): count for stars, count in zip(range(1, 6), counts)}


# Posición del local en su categoría (1 = mejor).
# GUIA #7 TEMA: Cadenas, listas, tuplas y diccionarios -> `lower()` compara la categoría sin importar mayúsculas.
async def category_rank(session: AsyncSession, establishment: Establishment) -> int | None:
    """Posición del local entre los aprobados de su misma categoría por `ranking_score`.

    1 + cantidad de locales con puntaje mayor (los empates comparten puesto). None si el local no
    está aprobado o aún no tiene puntaje.
    """
    if establishment.status != "APPROVED" or establishment.ranking_score is None:
        return None
    better = await session.scalar(
        select(func.count(Establishment.id)).where(
            Establishment.status == "APPROVED",
            func.lower(Establishment.category) == establishment.category.lower(),
            Establishment.ranking_score > establishment.ranking_score,
        )
    )
    return 1 + int(better or 0)
