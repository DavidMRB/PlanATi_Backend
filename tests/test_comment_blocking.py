"""B5: bloquear el comentario de una reseña o la respuesta del establecimiento.

Ninguna ruta pública ni del panel del establecimiento devuelve el texto bloqueado; las estrellas
siguen contando en el promedio; el autor (y el admin) ven el texto original.
"""

from app.models.review import BLOCKED_COMMENT_NOTICE, BLOCKED_REPLY_NOTICE
from tests.conftest import API
from tests.moderation_helpers import actions, detail, image, notifications, post_review

SECRET = "Texto con insultos al mesero Juan"


def _setup(approved_restaurant, user_client, add_reviews):
    owner_client, establishment_id = approved_restaurant("a")
    add_reviews(establishment_id, [2])
    author, author_id = user_client("u")
    review = post_review(author, establishment_id, rating=5, comment=SECRET, image_urls=[image("foto")])
    return owner_client, establishment_id, author, author_id, review


def _block(admin_client, review_id: int, **body):
    body.setdefault("category", "OFFENSIVE_LANGUAGE")
    return admin_client.post(f"{API}/admin/reviews/{review_id}/block-comment", json=body)


def test_blocked_comment_is_hidden_everywhere_public(
    admin_client, approved_restaurant, user_client, add_reviews, make_client
) -> None:
    owner_client, establishment_id, author, _, review = _setup(approved_restaurant, user_client, add_reviews)
    anonymous = make_client()
    before = detail(anonymous, establishment_id)

    response = _block(admin_client, review["id"], note="Contiene insultos al personal.")
    assert response.status_code == 200, response.text
    admin_view = response.json()
    assert admin_view["comment"] == SECRET and admin_view["comment_status"] == "BLOCKED"
    assert admin_view["moderation_category"] == "OFFENSIVE_LANGUAGE"

    public = detail(anonymous, establishment_id)
    [recent] = [r for r in public["recent_reviews"] if r["id"] == review["id"]]
    paged = anonymous.get(f"{API}/reviews/establishments/{establishment_id}").json()["items"]
    panel = owner_client.get(f"{API}/restaurant/reviews").json()["items"]
    for item in (recent, *[r for r in paged if r["id"] == review["id"]], *[r for r in panel if r["id"] == review["id"]]):
        assert item["comment"] is None
        assert item["comment_blocked"] is True
        assert item["moderation_notice"] == BLOCKED_COMMENT_NOTICE
        assert len(item["images"]) == 1  # sin remove_images, las fotos se conservan
    for client in (anonymous, owner_client):
        for path in (f"/establishments/{establishment_id}", f"/reviews/establishments/{establishment_id}"):
            assert SECRET not in client.get(f"{API}{path}").text
    assert SECRET not in owner_client.get(f"{API}/restaurant/reviews").text

    # Las estrellas siguen contando: el promedio no cambia.
    assert public["average_rating"] == before["average_rating"] == 3.5
    assert public["reviews_count"] == 2

    # El autor ve su texto original con el estado de moderación.
    [mine] = author.get(f"{API}/reviews/me").json()["items"]
    assert mine["comment"] == SECRET and mine["comment_blocked"] is True
    assert mine["moderation_category"] == "OFFENSIVE_LANGUAGE"
    assert mine["moderation_reason"] == "Contiene insultos al personal."
    assert detail(author, establishment_id)["viewer_review"]["comment"] == SECRET

    [notice] = [n for n in notifications(author) if n["type"] == "CONTENT_MODERATED"]
    assert "Lenguaje ofensivo o insultos" in notice["body"]
    assert notice["link"] == "/legal/community-guidelines"


def test_block_logs_copy_and_conflicts(admin_client, approved_restaurant, user_client, add_reviews, db_session) -> None:
    _, _, _, _, review = _setup(approved_restaurant, user_client, add_reviews)
    assert _block(admin_client, review["id"]).status_code == 200
    assert _block(admin_client, review["id"]).status_code == 409
    [entry] = actions(db_session, action="BLOCK_COMMENT")
    assert entry.details["comment"] == SECRET and entry.details["category"] == "OFFENSIVE_LANGUAGE"
    assert _block(admin_client, review["id"], category="NO_EXISTE").status_code == 422
    assert _block(admin_client, 9999).status_code == 404
    dashboard = admin_client.get(f"{API}/admin/dashboard").json()
    assert dashboard["blocked_comments"] == 1


def test_block_with_remove_images(admin_client, approved_restaurant, user_client, add_reviews, db_session) -> None:
    _, establishment_id, _, _, review = _setup(approved_restaurant, user_client, add_reviews)
    body = _block(admin_client, review["id"], category="PERSONAL_DATA", remove_images=True).json()
    assert body["images"] == []
    [entry] = actions(db_session, action="BLOCK_COMMENT")
    assert entry.details["removed_images"] == [image("foto")]


def test_review_without_comment_cannot_be_blocked(admin_client, approved_restaurant, user_client) -> None:
    _, establishment_id = approved_restaurant("a")
    author, _ = user_client("u")
    review = post_review(author, establishment_id, rating=3)
    assert _block(admin_client, review["id"]).status_code == 400


def test_rewriting_a_blocked_comment_keeps_it_blocked_and_flags_it(
    admin_client, approved_restaurant, user_client, add_reviews, make_client
) -> None:
    _, establishment_id, author, _, review = _setup(approved_restaurant, user_client, add_reviews)
    _block(admin_client, review["id"])

    edited = author.patch(f"{API}/reviews/{review['id']}", json={"comment": "Versión corregida"})
    assert edited.status_code == 200
    assert edited.json()["flagged_for_review"] is True and edited.json()["comment_blocked"] is True
    public = make_client().get(f"{API}/reviews/establishments/{establishment_id}").json()["items"]
    assert "Versión corregida" not in str(public)

    queue = admin_client.get(f"{API}/admin/reviews", params={"flagged_for_review": True}).json()
    assert [item["id"] for item in queue["items"]] == [review["id"]]
    assert queue["items"][0]["comment"] == "Versión corregida"
    assert admin_client.get(f"{API}/admin/dashboard").json()["flagged_for_review"] == 1

    # Aprobar el comentario reescrito: se publica y sale de la cola.
    unblocked = admin_client.post(f"{API}/admin/reviews/{review['id']}/unblock-comment", json={"note": "Gracias"})
    assert unblocked.status_code == 200
    assert unblocked.json()["comment_status"] == "VISIBLE" and unblocked.json()["flagged_for_review"] is False
    public = make_client().get(f"{API}/reviews/establishments/{establishment_id}").json()["items"]
    [item] = [r for r in public if r["id"] == review["id"]]
    assert item["comment"] == "Versión corregida" and item["comment_blocked"] is False
    assert admin_client.get(f"{API}/admin/reviews", params={"flagged_for_review": True}).json()["total"] == 0
    assert "CONTENT_RESTORED" in [n["type"] for n in notifications(author)]
    assert admin_client.post(f"{API}/admin/reviews/{review['id']}/unblock-comment").status_code == 409


def test_flagged_comment_can_be_blocked_again(admin_client, approved_restaurant, user_client, add_reviews) -> None:
    _, _, author, _, review = _setup(approved_restaurant, user_client, add_reviews)
    _block(admin_client, review["id"])
    author.patch(f"{API}/reviews/{review['id']}", json={"comment": "Sigue con insultos"})
    again = _block(admin_client, review["id"], note="El texto nuevo tampoco cumple.")
    assert again.status_code == 200 and again.json()["flagged_for_review"] is False


def test_block_and_unblock_reply(admin_client, approved_restaurant, user_client, make_client, db_session) -> None:
    owner_client, establishment_id = approved_restaurant("a")
    author, _ = user_client("u")
    review = post_review(author, establishment_id, rating=4, comment="Bien")
    reply_secret = "Respuesta con datos personales del cliente"
    owner_client.put(f"{API}/restaurant/reviews/{review['id']}/reply", json={"comment": reply_secret})
    reply_id = admin_client.get(f"{API}/admin/reviews").json()["items"][0]["reply"]["id"]

    blocked = admin_client.post(
        f"{API}/admin/review-replies/{reply_id}/block", json={"category": "PERSONAL_DATA", "note": "Datos del cliente"}
    )
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["reply"]["comment"] == reply_secret
    assert blocked.json()["reply"]["comment_status"] == "BLOCKED"

    anonymous = make_client()
    for client in (anonymous, owner_client, author):
        for path in (f"/establishments/{establishment_id}", f"/reviews/establishments/{establishment_id}"):
            assert reply_secret not in client.get(f"{API}{path}").text
    panel = owner_client.get(f"{API}/restaurant/reviews").json()["items"][0]["reply"]
    assert panel["comment"] is None and panel["comment_blocked"] is True
    assert panel["moderation_notice"] == BLOCKED_REPLY_NOTICE
    assert "CONTENT_MODERATED" in [n["type"] for n in notifications(owner_client)]
    assert admin_client.post(f"{API}/admin/review-replies/{reply_id}/block", json={"category": "OTHER"}).status_code == 409

    # Reescribir la respuesta bloqueada la deja bloqueada y pendiente de revisión.
    owner_client.put(f"{API}/restaurant/reviews/{review['id']}/reply", json={"comment": "Gracias por venir"})
    queue = admin_client.get(f"{API}/admin/reviews", params={"flagged_for_review": True}).json()["items"]
    assert queue[0]["reply"]["flagged_for_review"] is True
    assert queue[0]["reply"]["comment"] == "Gracias por venir"

    unblocked = admin_client.post(f"{API}/admin/review-replies/{reply_id}/unblock")
    assert unblocked.status_code == 200 and unblocked.json()["reply"]["comment_status"] == "VISIBLE"
    public_reply = anonymous.get(f"{API}/reviews/establishments/{establishment_id}").json()["items"][0]["reply"]
    assert public_reply["comment"] == "Gracias por venir"
    assert [entry.action for entry in actions(db_session, target_type="REVIEW_REPLY")] == ["BLOCK_REPLY", "UNBLOCK_REPLY"]
    assert admin_client.post(f"{API}/admin/review-replies/9999/unblock").status_code == 404
