"""Agregados y ranking bayesiano (adelantados a B2; B3 añade moderación y edición de reseñas)."""

import asyncio

import pytest
from sqlalchemy import select

from app.models.establishment import Establishment
from app.services.rating_service import bayesian_score, recompute_all_ratings, relevance_score
from tests.conftest import API


@pytest.mark.parametrize(
    ("rating_sum", "rating_count", "expected"),
    [
        (5, 1, 3.75),  # A: una sola reseña de 5★
        (184, 40, 4.48),  # B: 40 reseñas con promedio 4,6
        (0, 0, 3.5),  # C: sin reseñas, parte del valor previo
        (30, 12, 2.79),  # D: 12 reseñas con promedio 2,5
    ],
)
def test_bayesian_score_examples_from_the_plan(rating_sum: int, rating_count: int, expected: float) -> None:
    assert bayesian_score(rating_sum, rating_count, min_reviews=5, prior_mean=3.5) == pytest.approx(expected, abs=0.005)


def test_bayesian_score_ranks_volume_over_a_single_perfect_review() -> None:
    assert bayesian_score(184, 40) > bayesian_score(5, 1) > bayesian_score(0, 0) > bayesian_score(30, 12)


def test_relevance_score_mixes_rating_and_closeness() -> None:
    # Con el mismo ranking, el más cercano es más relevante.
    assert relevance_score(4.0, 1, 5, weight=0.6) > relevance_score(4.0, 4, 5, weight=0.6)
    # Peso 1: solo cuenta la puntuación; peso 0: solo la cercanía.
    assert relevance_score(5.0, 5, 5, weight=1) == pytest.approx(1)
    assert relevance_score(1.0, 0, 5, weight=0) == pytest.approx(1)
    # Más allá del radio la cercanía no resta por debajo de cero.
    assert relevance_score(3.0, 50, 5, weight=0) == 0


def test_creating_a_review_updates_aggregates_in_the_same_request(approved_restaurant, user_client) -> None:
    owner, establishment_id = approved_restaurant("a")
    client, _ = user_client("a")
    response = client.post(f"{API}/reviews/establishments/{establishment_id}", json={"rating": 4, "comment": "Muy bien"})
    assert response.status_code == 201, response.text

    profile = owner.get(f"{API}/restaurant/profile").json()
    assert (profile["rating_count"], profile["rating_avg"]) == (1, 4.0)
    assert profile["ranking_score"] == pytest.approx(bayesian_score(4, 1))

    other, _ = user_client("b")
    other.post(f"{API}/reviews/establishments/{establishment_id}", json={"rating": 1, "comment": "Mal"})
    listing = owner.get(f"{API}/establishments").json()
    assert (listing[0]["rating_count"], listing[0]["rating_avg"]) == (2, 2.5)


def test_recompute_all_ratings_fixes_drift(approved_restaurant, add_reviews, db_session) -> None:
    _, rated = approved_restaurant("a")
    _, unrated = approved_restaurant("b")
    add_reviews(rated, [5, 3])

    async def corrupt_and_recompute() -> dict[int, tuple[int, int, float | None, float | None]]:
        async with db_session() as session:
            for establishment in (await session.scalars(select(Establishment))).all():
                establishment.rating_count, establishment.rating_sum = 99, 1
                establishment.rating_avg, establishment.ranking_score = 0.1, None
            await session.commit()
        async with db_session() as session:
            assert await recompute_all_ratings(session) == 2
            await session.commit()
        async with db_session() as session:
            rows = (await session.scalars(select(Establishment))).all()
            return {e.id: (e.rating_count, e.rating_sum, e.rating_avg, e.ranking_score) for e in rows}

    result = asyncio.run(corrupt_and_recompute())
    assert result[rated] == (2, 8, 4.0, pytest.approx(bayesian_score(8, 2)))
    assert result[unrated] == (0, 0, None, 3.5)
