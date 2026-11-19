"""Reseñas de la fase B3: permisos, validaciones, edición, borrado, listado, agregados y detalle."""

import asyncio

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.notification import Notification
from app.models.review import BLOCKED_COMMENT_NOTICE, Review
from app.services.rating_service import bayesian_score, recalculate_establishment_rating
from tests.conftest import API, login


def image(name: str) -> str:
    return f"{settings.r2_public_base_url.rstrip('/')}/reviews/{name}.jpg"


def post_review(client, establishment_id: int, **body):
    body.setdefault("rating", 4)
    return client.post(f"{API}/reviews/establishments/{establishment_id}", json=body)


def detail(client, establishment_id: int) -> dict:
    response = client.get(f"{API}/establishments/{establishment_id}")
    assert response.status_code == 200, response.text
    return response.json()


def set_review_fields(db_session, review_id: int, **fields) -> None:
    """Simula la moderación de B5 (ocultar, restaurar, bloquear) directamente en la base de datos."""

    async def scenario() -> None:
        async with db_session() as session:
            review = await session.get(Review, review_id)
            for name, value in fields.items():
                setattr(review, name, value)
            await session.flush()
            await recalculate_establishment_rating(session, review.establishment_id)
            await session.commit()

    asyncio.run(scenario())


# --- Permisos -----------------------------------------------------------------------------------


def test_permission_matrix(approved_restaurant, register_restaurant, user_client, make_client, create_user, admin_client) -> None:
    owner, establishment_id = approved_restaurant("a")
    _, pending = register_restaurant("p")
    pending_id = pending["establishment_id"]

    visitor = make_client()
    assert post_review(visitor, establishment_id).status_code == 401

    create_user("sin-telefono@planati.com", phone_verified=False, status="PENDING_PHONE")
    unverified = make_client()
    login(unverified, "sin-telefono@planati.com")
    response = post_review(unverified, establishment_id)
    assert response.status_code == 403
    assert response.json()["code"] == "PHONE_NOT_VERIFIED"

    assert post_review(owner, establishment_id).json()["code"] == "ROLE_NOT_ALLOWED"
    assert post_review(admin_client, establishment_id).status_code == 403

    client, _ = user_client("a")
    assert post_review(client, pending_id).status_code == 404
    assert post_review(client, 999_999).status_code == 404
    assert client.get(f"{API}/reviews/establishments/{pending_id}").status_code == 404


def test_owner_of_a_legacy_establishment_cannot_review_it(user_client, admin_client) -> None:
    client, _ = user_client("dueno")
    created = client.post(
        f"{API}/establishments",
        json={"name": "Café Propio", "category": "Café", "description": "Café", "address": "Calle 10, Cúcuta"},
    )
    assert created.status_code == 201, created.text
    establishment_id = created.json()["id"]
    assert admin_client.post(f"{API}/admin/establishments/{establishment_id}/approve").status_code == 200

    response = post_review(client, establishment_id)
    assert response.status_code == 403
    assert response.json()["code"] == "OWNER"
    body = detail(client, establishment_id)
    assert (body["viewer_can_review"], body["viewer_review_block"]) == (False, "OWNER")


def test_viewer_flags_in_detail(approved_restaurant, user_client, make_client) -> None:
    owner, establishment_id = approved_restaurant("a")
    client, _ = user_client("a")

    anonymous = detail(make_client(), establishment_id)
    assert (anonymous["viewer_can_review"], anonymous["viewer_review_block"]) == (False, "LOGIN_REQUIRED")
    assert anonymous["viewer_review"] is None
    assert detail(owner, establishment_id)["viewer_review_block"] == "ROLE_NOT_ALLOWED"

    before = detail(client, establishment_id)
    assert (before["viewer_can_review"], before["viewer_review_block"]) == (True, None)

    review_id = post_review(client, establishment_id, rating=5, comment="Excelente").json()["id"]
    after = detail(client, establishment_id)
    assert (after["viewer_can_review"], after["viewer_review_block"]) == (False, "ALREADY_REVIEWED")
    assert after["viewer_review"]["id"] == review_id
    assert "reviews" not in after


# --- Crear --------------------------------------------------------------------------------------


def test_duplicate_review_returns_409_with_review_id(approved_restaurant, user_client) -> None:
    _, establishment_id = approved_restaurant("a")
    client, _ = user_client("a")
    first = post_review(client, establishment_id)
    assert first.status_code == 201
    second = post_review(client, establishment_id, rating=1)
    assert second.status_code == 409
    assert second.json() == {"detail": "Ya reseñaste este lugar. Puedes editar tu reseña.", "review_id": first.json()["id"]}


def test_comment_is_optional_and_stripped(approved_restaurant, user_client) -> None:
    _, establishment_id = approved_restaurant("a")
    a, _ = user_client("a")
    b, _ = user_client("b")
    only_stars = post_review(a, establishment_id, rating=5)
    assert only_stars.status_code == 201
    assert only_stars.json()["comment"] is None
    blank = post_review(b, establishment_id, rating=3, comment="   ")
    assert blank.json()["comment"] is None


def test_review_author_is_public_display_name_only(approved_restaurant, user_client, create_user, make_client) -> None:
    _, establishment_id = approved_restaurant("a")
    create_user("laura@planati.com", full_name="Laura María Gómez", phone_number="+573009999999")
    client = make_client()
    login(client, "laura@planati.com")
    body = post_review(client, establishment_id, comment="Rico").json()
    assert body["author"]["display_name"] == "Laura G."
    assert set(body["author"]) == {"id", "display_name", "picture"}

    nick, _ = user_client("n")  # nickname "usuarion"
    assert post_review(nick, establishment_id).json()["author"]["display_name"] == "usuarion"


@pytest.mark.parametrize(
    "body",
    [
        {"rating": 0},
        {"rating": 6},
        {"rating": 4.5},
        {"rating": 4, "comment": "x" * 2001},
        {"rating": 4, "image_urls": ["https://otro-dominio.com/reviews/a.jpg"]},
        {"rating": 4, "image_urls": [image("a"), image("a")]},
        {"rating": 4, "image_urls": [image(str(n)) for n in range(6)]},
    ],
)
def test_review_validation_422(approved_restaurant, user_client, body) -> None:
    _, establishment_id = approved_restaurant("a")
    client, _ = user_client("a")
    assert client.post(f"{API}/reviews/establishments/{establishment_id}", json=body).status_code == 422


def test_review_with_images(approved_restaurant, user_client) -> None:
    _, establishment_id = approved_restaurant("a")
    client, _ = user_client("a")
    urls = [image("uno"), image("dos")]
    body = post_review(client, establishment_id, rating=5, comment="Con fotos", image_urls=urls).json()
    assert [img["image_url"] for img in body["images"]] == urls
    assert [img["display_order"] for img in body["images"]] == [0, 1]


def test_daily_limit_returns_429(approved_restaurant, user_client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "reviews_per_day_limit", 2)
    ids = [approved_restaurant(s)[1] for s in ("a", "b", "c")]
    client, _ = user_client("a")
    assert post_review(client, ids[0]).status_code == 201
    assert post_review(client, ids[1]).status_code == 201
    response = post_review(client, ids[2])
    assert response.status_code == 429
    assert "límite diario" in response.json()["detail"]


def test_owner_is_notified_of_new_review(approved_restaurant, user_client) -> None:
    owner, establishment_id = approved_restaurant("a")
    client, _ = user_client("a")
    review_id = post_review(client, establishment_id, rating=5).json()["id"]
    items = owner.get(f"{API}/notifications").json()["items"]
    received = [n for n in items if n["type"] == "REVIEW_RECEIVED"]
    assert len(received) == 1
    assert received[0]["link"] == "/restaurant/reviews"
    assert received[0]["data"]["review_id"] == review_id


# --- Editar y eliminar --------------------------------------------------------------------------


def test_edit_and_delete_own_review_update_aggregates(approved_restaurant, user_client, add_reviews, make_client) -> None:
    _, establishment_id = approved_restaurant("a")
    add_reviews(establishment_id, [2])
    client, _ = user_client("a")
    review_id = post_review(client, establishment_id, rating=4, comment="Bien").json()["id"]
    assert (detail(client, establishment_id)["reviews_count"], detail(client, establishment_id)["average_rating"]) == (2, 3.0)

    edited = client.patch(f"{API}/reviews/{review_id}", json={"rating": 5, "comment": "Mejor de lo que pensé", "image_urls": [image("x")]})
    assert edited.status_code == 200, edited.text
    body = edited.json()
    assert (body["rating"], body["comment"], body["edited_at"] is not None) == (5, "Mejor de lo que pensé", True)
    assert [img["image_url"] for img in body["images"]] == [image("x")]
    after_edit = detail(make_client(), establishment_id)
    assert (after_edit["reviews_count"], after_edit["average_rating"]) == (2, 3.5)
    assert after_edit["ranking_score"] == pytest.approx(bayesian_score(7, 2))

    # Quitar el texto y las imágenes.
    cleared = client.patch(f"{API}/reviews/{review_id}", json={"comment": None, "image_urls": []}).json()
    assert (cleared["comment"], cleared["images"]) == (None, [])

    assert client.delete(f"{API}/reviews/{review_id}").status_code == 204
    after_delete = detail(make_client(), establishment_id)
    assert (after_delete["reviews_count"], after_delete["average_rating"]) == (1, 2.0)
    # Tras borrarla puede volver a reseñar.
    assert post_review(client, establishment_id).status_code == 201


def test_cannot_edit_or_delete_someone_elses_review(approved_restaurant, user_client) -> None:
    _, establishment_id = approved_restaurant("a")
    author, _ = user_client("a")
    other, _ = user_client("b")
    review_id = post_review(author, establishment_id).json()["id"]
    assert other.patch(f"{API}/reviews/{review_id}", json={"rating": 1}).status_code == 404
    assert other.delete(f"{API}/reviews/{review_id}").status_code == 404
    assert other.patch(f"{API}/reviews/999999", json={"rating": 1}).status_code == 404


def test_rating_cannot_be_set_to_null(approved_restaurant, user_client) -> None:
    _, establishment_id = approved_restaurant("a")
    client, _ = user_client("a")
    review_id = post_review(client, establishment_id).json()["id"]
    assert client.patch(f"{API}/reviews/{review_id}", json={"rating": None}).status_code == 422


def test_hidden_review_cannot_be_edited(approved_restaurant, user_client, db_session) -> None:
    _, establishment_id = approved_restaurant("a")
    client, _ = user_client("a")
    review_id = post_review(client, establishment_id).json()["id"]
    set_review_fields(db_session, review_id, status="HIDDEN", moderation_reason="Spam")
    response = client.patch(f"{API}/reviews/{review_id}", json={"rating": 5})
    assert response.status_code == 403
    assert response.json()["detail"] == "Esta reseña fue ocultada por moderación y no puede editarse."
    # El autor la sigue viendo con el motivo; el detalle se la muestra en viewer_review.
    mine = client.get(f"{API}/reviews/me").json()["items"][0]
    assert (mine["status"], mine["moderation_reason"]) == ("HIDDEN", "Spam")
    assert detail(client, establishment_id)["viewer_review"]["status"] == "HIDDEN"


# --- Agregados con moderación -------------------------------------------------------------------


def test_hide_and_restore_recalculate_but_blocking_does_not(approved_restaurant, user_client, add_reviews, db_session, make_client) -> None:
    _, establishment_id = approved_restaurant("a")
    add_reviews(establishment_id, [5])
    client, _ = user_client("a")
    review_id = post_review(client, establishment_id, rating=1, comment="Pésimo, idiotas").json()["id"]
    visitor = make_client()
    assert detail(visitor, establishment_id)["average_rating"] == 3.0

    set_review_fields(db_session, review_id, status="HIDDEN")
    hidden = detail(visitor, establishment_id)
    assert (hidden["reviews_count"], hidden["average_rating"]) == (1, 5.0)
    assert hidden["rating_distribution"] == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 1}
    assert visitor.get(f"{API}/reviews/establishments/{establishment_id}").json()["total"] == 1

    set_review_fields(db_session, review_id, status="VISIBLE")
    assert detail(visitor, establishment_id)["average_rating"] == 3.0

    set_review_fields(db_session, review_id, comment_status="BLOCKED", moderation_category="OFFENSIVE_LANGUAGE")
    blocked = detail(visitor, establishment_id)
    assert (blocked["reviews_count"], blocked["average_rating"]) == (2, 3.0)
    public = next(r for r in blocked["recent_reviews"] if r["id"] == review_id)
    assert (public["comment"], public["comment_blocked"], public["moderation_notice"]) == (None, True, BLOCKED_COMMENT_NOTICE)
    listed = visitor.get(f"{API}/reviews/establishments/{establishment_id}").json()["items"]
    assert next(r for r in listed if r["id"] == review_id)["comment"] is None

    # El autor ve su texto original y, si lo reescribe, queda pendiente de revisión y sigue bloqueado.
    mine = client.get(f"{API}/reviews/me").json()["items"][0]
    assert (mine["comment"], mine["comment_status"], mine["moderation_category"]) == ("Pésimo, idiotas", "BLOCKED", "OFFENSIVE_LANGUAGE")
    rewritten = client.patch(f"{API}/reviews/{review_id}", json={"comment": "No me gustó"}).json()
    assert (rewritten["comment"], rewritten["flagged_for_review"], rewritten["comment_blocked"]) == ("No me gustó", True, True)
    assert next(r for r in detail(visitor, establishment_id)["recent_reviews"] if r["id"] == review_id)["comment"] is None


# --- Listado y detalle --------------------------------------------------------------------------


def test_list_pagination_sort_and_filters(approved_restaurant, user_client) -> None:
    _, establishment_id = approved_restaurant("a")
    ratings = [3, 5, 1, 4]
    ids = []
    for index, rating in enumerate(ratings):
        client, _ = user_client(f"u{index}")
        images = [image(f"f{index}")] if rating >= 4 else []
        ids.append(post_review(client, establishment_id, rating=rating, image_urls=images).json()["id"])

    url = f"{API}/reviews/establishments/{establishment_id}"
    page = client.get(url, params={"limit": 2}).json()
    assert (page["total"], page["skip"], page["limit"], len(page["items"])) == (4, 0, 2, 2)
    assert [r["id"] for r in page["items"]] == [ids[3], ids[2]]  # más recientes primero
    assert [r["rating"] for r in client.get(url, params={"sort": "rating_desc"}).json()["items"]] == [5, 4, 3, 1]
    assert [r["rating"] for r in client.get(url, params={"sort": "rating_asc"}).json()["items"]] == [1, 3, 4, 5]
    assert [r["id"] for r in client.get(url, params={"rating": 5}).json()["items"]] == [ids[1]]
    with_photos = client.get(url, params={"with_photos": True}).json()
    assert (with_photos["total"], {r["rating"] for r in with_photos["items"]}) == (2, {4, 5})
    assert client.get(url, params={"limit": 51}).status_code == 422


def test_detail_summary_recent_reviews_and_category_rank(approved_restaurant, add_reviews, make_client) -> None:
    _, best = approved_restaurant("a")
    _, second = approved_restaurant("b")
    _, other_category = approved_restaurant("c", category="Café")
    add_reviews(best, [5, 5, 5, 4, 5])
    add_reviews(second, [4, 2])

    body = detail(make_client(), second)
    assert (body["reviews_count"], body["average_rating"]) == (2, 3.0)
    assert body["rating_distribution"] == {"1": 0, "2": 1, "3": 0, "4": 1, "5": 0}
    assert body["category_rank"] == 2
    assert detail(make_client(), best)["category_rank"] == 1
    assert detail(make_client(), other_category)["category_rank"] == 1

    top = detail(make_client(), best)
    assert len(top["recent_reviews"]) == 3
    assert set(top["recent_reviews"][0]["author"]) == {"id", "display_name", "picture"}


def test_my_reviews_lists_establishment_summary(approved_restaurant, user_client) -> None:
    _, a = approved_restaurant("a")
    _, b = approved_restaurant("b")
    client, _ = user_client("a")
    post_review(client, a, rating=3)
    post_review(client, b, rating=5)
    page = client.get(f"{API}/reviews/me").json()
    assert page["total"] == 2
    assert [item["establishment"]["name"] for item in page["items"]] == ["Parrilla B", "Parrilla A"]
    assert user_client("b")[0].get(f"{API}/reviews/me").json()["total"] == 0


def test_restaurant_profile_no_longer_includes_reviews(approved_restaurant, user_client) -> None:
    owner, establishment_id = approved_restaurant("a")
    post_review(user_client("a")[0], establishment_id)
    assert "reviews" not in owner.get(f"{API}/restaurant/profile").json()


# --- Subida de imágenes y rutas legadas ---------------------------------------------------------


def test_upload_url_requires_reviewer(approved_restaurant, user_client, make_client) -> None:
    owner, _ = approved_restaurant("a")
    client, _ = user_client("a")
    assert make_client().post(f"{API}/reviews/upload-url").status_code == 401
    assert owner.post(f"{API}/reviews/upload-url").status_code == 403
    # En las pruebas R2 no está configurado: 503 (el frontend permite publicar sin fotos).
    assert client.post(f"{API}/reviews/upload-url", params={"file_extension": ".png"}).status_code in (200, 503)


def test_legacy_reply_twice_updates_instead_of_500(approved_restaurant, user_client, db_session) -> None:
    owner, establishment_id = approved_restaurant("a")
    client, _ = user_client("a")
    review_id = post_review(client, establishment_id).json()["id"]

    first = owner.post(f"{API}/reviews/{review_id}/reply", json={"comment": "¡Gracias!"})
    assert first.status_code == 200, first.text
    second = owner.post(f"{API}/reviews/{review_id}/reply", json={"comment": "¡Gracias por venir!"})
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["comment"] == "¡Gracias por venir!"

    async def replied_notifications() -> int:
        async with db_session() as session:
            rows = await session.scalars(select(Notification).where(Notification.type == "REVIEW_REPLIED"))
            return len(rows.all())

    assert asyncio.run(replied_notifications()) == 1
    assert detail(client, establishment_id)["recent_reviews"][0]["reply"]["comment"] == "¡Gracias por venir!"


def test_legacy_add_image_validates_url_and_maximum(approved_restaurant, user_client, monkeypatch) -> None:
    monkeypatch.setattr(settings, "review_max_images", 1)
    _, establishment_id = approved_restaurant("a")
    client, _ = user_client("a")
    review_id = post_review(client, establishment_id).json()["id"]
    url = f"{API}/reviews/{review_id}/images"
    assert client.post(url, json={"image_url": "https://malo.com/x.jpg"}).status_code == 422
    assert client.post(url, json={"image_url": image("a")}).status_code == 201
    assert client.post(url, json={"image_url": image("b")}).status_code == 400


def test_daily_limit_only_counts_reviews_of_the_local_day(approved_restaurant, user_client, db_session, monkeypatch) -> None:
    from datetime import timedelta

    from app.core.time import local_day_start

    monkeypatch.setattr(settings, "reviews_per_day_limit", 1)
    _, first = approved_restaurant("a")
    _, second = approved_restaurant("b")
    client, _ = user_client("a")
    review_id = post_review(client, first).json()["id"]
    # Un minuto antes de la medianoche de Colombia: es de ayer y no cuenta.
    set_review_fields(db_session, review_id, created_at=local_day_start() - timedelta(minutes=1))
    assert post_review(client, second).status_code == 201
