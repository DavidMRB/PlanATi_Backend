"""Panel del establecimiento: reseñas, resumen y respuestas (fase B4)."""

import asyncio

from sqlalchemy import select

from app.models.notification import Notification
from app.models.review import BLOCKED_COMMENT_NOTICE, BLOCKED_REPLY_NOTICE, Review, ReviewReply
from app.services.rating_service import recalculate_establishment_rating
from tests.conftest import API


def review(client, establishment_id: int, rating: int = 4, comment: str | None = "Bien") -> int:
    response = client.post(f"{API}/reviews/establishments/{establishment_id}", json={"rating": rating, "comment": comment})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def reply(client, review_id: int, comment: str):
    return client.put(f"{API}/restaurant/reviews/{review_id}/reply", json={"comment": comment})


def update_rows(db_session, model, row_id: int, **fields) -> None:
    async def scenario() -> None:
        async with db_session() as session:
            row = await session.get(model, row_id)
            for name, value in fields.items():
                setattr(row, name, value)
            await session.flush()
            if model is Review:
                await recalculate_establishment_rating(session, row.establishment_id)
            await session.commit()

    asyncio.run(scenario())


def replied_notifications(db_session, user_id: int) -> int:
    async def scenario() -> int:
        async with db_session() as session:
            rows = await session.scalars(
                select(Notification).where(Notification.user_id == user_id, Notification.type == "REVIEW_REPLIED")
            )
            return len(rows.all())

    return asyncio.run(scenario())


def test_reply_twice_updates_and_notifies_only_once(approved_restaurant, user_client, db_session) -> None:
    owner, establishment_id = approved_restaurant("a")
    author, author_id = user_client("a")
    review_id = review(author, establishment_id)

    first = reply(owner, review_id, "  ¡Gracias por visitarnos!  ")
    assert first.status_code == 200, first.text
    assert first.json()["reply"]["comment"] == "¡Gracias por visitarnos!"
    second = reply(owner, review_id, "¡Gracias, vuelve pronto!")
    assert second.status_code == 200
    assert second.json()["reply"]["id"] == first.json()["reply"]["id"]
    assert second.json()["reply"]["comment"] == "¡Gracias, vuelve pronto!"
    assert replied_notifications(db_session, author_id) == 1

    link = author.get(f"{API}/notifications").json()["items"][0]["link"]
    assert link == f"/establishments/{establishment_id}#review-{review_id}"

    # Borrar y volver a responder no vuelve a notificar.
    assert owner.delete(f"{API}/restaurant/reviews/{review_id}/reply").status_code == 204
    assert reply(owner, review_id, "Otra vez gracias").status_code == 200
    assert replied_notifications(db_session, author_id) == 1


def test_reply_validation_and_isolation(approved_restaurant, user_client, db_session) -> None:
    owner, establishment_id = approved_restaurant("a")
    other_owner, other_id = approved_restaurant("b")
    author, _ = user_client("a")
    review_id = review(author, establishment_id)
    other_review = review(author, other_id)

    assert reply(owner, review_id, "   ").status_code == 422
    assert reply(owner, review_id, "x" * 1001).status_code == 422
    assert reply(owner, other_review, "No es mía").status_code == 404
    assert reply(owner, 999_999, "No existe").status_code == 404
    assert owner.delete(f"{API}/restaurant/reviews/{review_id}/reply").status_code == 404
    # Un usuario normal no entra al panel.
    assert reply(author, review_id, "Hola").status_code == 403

    update_rows(db_session, Review, review_id, status="HIDDEN")
    assert reply(owner, review_id, "Oculta").status_code == 404


def test_pending_restaurant_cannot_use_the_review_panel(register_restaurant) -> None:
    client, _ = register_restaurant("p")
    response = client.get(f"{API}/restaurant/reviews")
    assert response.status_code == 403
    assert response.json()["status"] == "PENDING"


def test_list_filters_and_never_returns_blocked_comment(approved_restaurant, user_client, db_session) -> None:
    owner, establishment_id = approved_restaurant("a")
    ids = []
    for index, rating in enumerate([5, 2, 4]):
        client, _ = user_client(f"u{index}")
        ids.append(review(client, establishment_id, rating=rating, comment=f"Comentario secreto {index}"))
    hidden_author, _ = user_client("h")
    hidden_id = review(hidden_author, establishment_id, rating=1)
    update_rows(db_session, Review, hidden_id, status="HIDDEN")
    update_rows(db_session, Review, ids[1], comment_status="BLOCKED", moderation_category="OFFENSIVE_LANGUAGE")
    reply(owner, ids[0], "Gracias")

    url = f"{API}/restaurant/reviews"
    page = owner.get(url).json()
    assert page["total"] == 3
    assert [r["id"] for r in page["items"]] == [ids[2], ids[1], ids[0]]
    assert [r["id"] for r in owner.get(url, params={"status": "unanswered"}).json()["items"]] == [ids[2], ids[1]]
    assert [r["id"] for r in owner.get(url, params={"status": "answered"}).json()["items"]] == [ids[0]]
    assert [r["rating"] for r in owner.get(url, params={"sort": "rating_asc"}).json()["items"]] == [2, 4, 5]
    assert [r["id"] for r in owner.get(url, params={"rating": 4}).json()["items"]] == [ids[2]]

    blocked = next(r for r in page["items"] if r["id"] == ids[1])
    assert (blocked["comment"], blocked["comment_blocked"], blocked["moderation_notice"]) == (None, True, BLOCKED_COMMENT_NOTICE)
    assert "Comentario secreto 1" not in owner.get(url).text
    # Puede responder a la calificación aunque el comentario esté bloqueado.
    assert reply(owner, ids[1], "Lamentamos tu experiencia").status_code == 200


def test_summary_counts_unanswered_and_response_rate(approved_restaurant, user_client) -> None:
    owner, establishment_id = approved_restaurant("a")
    empty = owner.get(f"{API}/restaurant/reviews/summary").json()
    assert (empty["rating_count"], empty["unanswered_count"], empty["response_rate"]) == (0, 0, None)
    assert empty["distribution"] == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}

    ids = [review(user_client(f"u{i}")[0], establishment_id, rating=r) for i, r in enumerate([5, 4, 4, 1])]
    for review_id in ids[:3]:
        reply(owner, review_id, "Gracias")
    summary = owner.get(f"{API}/restaurant/reviews/summary").json()
    assert summary == {
        "rating_avg": 3.5,
        "rating_count": 4,
        "ranking_score": summary["ranking_score"],
        "category_rank": 1,
        "distribution": {"1": 1, "2": 0, "3": 0, "4": 2, "5": 1},
        "unanswered_count": 1,
        "response_rate": 0.75,
    }


def test_blocked_reply_stays_blocked_when_edited(approved_restaurant, user_client, db_session) -> None:
    owner, establishment_id = approved_restaurant("a")
    author, _ = user_client("a")
    review_id = review(author, establishment_id)
    reply_id = reply(owner, review_id, "Texto ofensivo").json()["reply"]["id"]
    update_rows(db_session, ReviewReply, reply_id, comment_status="BLOCKED")

    edited = reply(owner, review_id, "Texto corregido").json()["reply"]
    assert (edited["comment"], edited["comment_blocked"], edited["moderation_notice"]) == (None, True, BLOCKED_REPLY_NOTICE)

    async def flagged() -> tuple[str, bool]:
        async with db_session() as session:
            row = await session.get(ReviewReply, reply_id)
            return row.comment, row.flagged_for_review

    assert asyncio.run(flagged()) == ("Texto corregido", True)
    public = author.get(f"{API}/reviews/establishments/{establishment_id}").json()["items"][0]["reply"]
    assert public["comment"] is None
