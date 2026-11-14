"""B5: ocultar, restaurar y borrar reseñas e imágenes; cola de moderación; acceso solo para admins."""

from tests.conftest import API
from tests.moderation_helpers import REASON, actions, detail, image, notifications, post_review


def _two_reviews(approved_restaurant, user_client):
    owner_client, establishment_id = approved_restaurant("a")
    client_u, user_u = user_client("u")
    client_v, _ = user_client("v")
    spam = post_review(client_u, establishment_id, rating=1, comment="Compra seguidores en mi página")
    good = post_review(client_v, establishment_id, rating=5, comment="Excelente servicio")
    return owner_client, establishment_id, client_u, user_u, spam, good


def test_hide_recalculates_average_and_notifies(admin_client, approved_restaurant, user_client, make_client) -> None:
    _, establishment_id, client_u, _, spam, good = _two_reviews(approved_restaurant, user_client)
    anonymous = make_client()
    assert detail(anonymous, establishment_id)["average_rating"] == 3.0

    response = admin_client.post(
        f"{API}/admin/reviews/{spam['id']}/hide", json={"category": "SPAM_OR_ADVERTISING", "reason": "Publicidad"}
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "HIDDEN"

    public = detail(anonymous, establishment_id)
    assert public["average_rating"] == 5.0 and public["reviews_count"] == 1
    public_ids = [r["id"] for r in anonymous.get(f"{API}/reviews/establishments/{establishment_id}").json()["items"]]
    assert public_ids == [good["id"]]
    [mine] = client_u.get(f"{API}/reviews/me").json()["items"]
    assert mine["status"] == "HIDDEN" and mine["moderation_reason"] == "Publicidad"
    assert client_u.patch(f"{API}/reviews/{spam['id']}", json={"rating": 5}).status_code == 403
    assert notifications(client_u)[0]["type"] == "CONTENT_MODERATED"
    assert admin_client.post(f"{API}/admin/reviews/{spam['id']}/hide", json={"category": "OTHER"}).status_code == 409
    assert admin_client.get(f"{API}/admin/dashboard").json()["hidden_reviews"] == 1

    restored = admin_client.post(f"{API}/admin/reviews/{spam['id']}/restore")
    assert restored.status_code == 200 and restored.json()["status"] == "VISIBLE"
    assert restored.json()["moderation_reason"] is None
    assert detail(anonymous, establishment_id)["average_rating"] == 3.0
    assert notifications(client_u)[0]["type"] == "CONTENT_RESTORED"
    assert admin_client.post(f"{API}/admin/reviews/{spam['id']}/restore").status_code == 409


def test_hide_accepts_note_alias(admin_client, approved_restaurant, user_client) -> None:
    _, _, _, _, spam, _ = _two_reviews(approved_restaurant, user_client)
    body = admin_client.post(
        f"{API}/admin/reviews/{spam['id']}/hide", json={"category": "SPAM_OR_ADVERTISING", "note": "Spam"}
    ).json()
    assert body["moderation_reason"] == "Spam"


def test_delete_review_keeps_snapshot_in_log(admin_client, approved_restaurant, user_client, make_client, db_session) -> None:
    _, establishment_id, client_u, user_u, spam, _ = _two_reviews(approved_restaurant, user_client)
    assert admin_client.delete(f"{API}/admin/reviews/{spam['id']}").status_code == 422  # el motivo es obligatorio
    response = admin_client.delete(f"{API}/admin/reviews/{spam['id']}", params={"reason": "Contenido ilegal"})
    assert response.status_code == 204
    assert client_u.get(f"{API}/reviews/me").json()["total"] == 0
    assert detail(make_client(), establishment_id)["average_rating"] == 5.0
    [entry] = actions(db_session, action="DELETE_REVIEW")
    assert entry.reason == "Contenido ilegal"
    assert entry.details["comment"] == "Compra seguidores en mi página"
    assert entry.details["rating"] == 1 and entry.details["user_id"] == user_u
    assert notifications(client_u)[0]["type"] == "CONTENT_MODERATED"
    assert admin_client.delete(f"{API}/admin/reviews/{spam['id']}", params={"reason": "Otra vez"}).status_code == 404


def test_delete_review_image(admin_client, approved_restaurant, user_client, db_session) -> None:
    _, establishment_id = approved_restaurant("a")
    author, _ = user_client("u")
    review = post_review(author, establishment_id, image_urls=[image("a"), image("b")])
    image_id = review["images"][0]["id"]
    response = admin_client.delete(f"{API}/admin/review-images/{image_id}", params={"reason": "Foto inapropiada"})
    assert response.status_code == 204
    [mine] = author.get(f"{API}/reviews/me").json()["items"]
    assert [img["image_url"] for img in mine["images"]] == [image("b")]
    [entry] = actions(db_session, action="DELETE_REVIEW_IMAGE")
    assert entry.details == {"review_id": review["id"], "image_url": image("a")}
    assert admin_client.delete(f"{API}/admin/review-images/{image_id}", params={"reason": REASON}).status_code == 404


def test_admin_review_queue_filters(admin_client, approved_restaurant, user_client) -> None:
    _, establishment_id, _, user_u, spam, good = _two_reviews(approved_restaurant, user_client)
    admin_client.post(f"{API}/admin/reviews/{spam['id']}/hide", json={"category": "SPAM_OR_ADVERTISING"})
    admin_client.post(f"{API}/admin/reviews/{good['id']}/block-comment", json={"category": "OTHER"})

    def ids(**params) -> list[int]:
        response = admin_client.get(f"{API}/admin/reviews", params=params)
        assert response.status_code == 200, response.text
        return [item["id"] for item in response.json()["items"]]

    assert set(ids()) == {spam["id"], good["id"]}
    assert ids(status="HIDDEN") == [spam["id"]]
    assert ids(comment_status="BLOCKED") == [good["id"]]
    assert ids(user_id=user_u) == [spam["id"]]
    assert ids(rating=5) == [good["id"]]
    assert ids(search="seguidores") == [spam["id"]]
    assert ids(establishment_id=establishment_id, has_reports=False) != []
    assert ids(has_reports=True) == []
    item = admin_client.get(f"{API}/admin/reviews", params={"comment_status": "BLOCKED"}).json()["items"][0]
    assert item["comment"] == "Excelente servicio"  # el admin siempre ve el texto original
    assert item["author"]["email"] == "usuario-v@planati.com"
    assert item["establishment"]["name"] == "Parrilla A"


def test_moderation_log_filters(admin_client, approved_restaurant, user_client) -> None:
    _, _, _, _, spam, good = _two_reviews(approved_restaurant, user_client)
    admin_client.post(f"{API}/admin/reviews/{spam['id']}/hide", json={"category": "SPAM_OR_ADVERTISING"})
    admin_client.post(f"{API}/admin/reviews/{good['id']}/block-comment", json={"category": "OTHER"})
    log = admin_client.get(f"{API}/admin/moderation-actions").json()
    assert [item["action"] for item in log["items"]] == ["BLOCK_COMMENT", "HIDE_REVIEW"]
    filtered = admin_client.get(f"{API}/admin/moderation-actions", params={"target_id": spam["id"], "target_type": "REVIEW"})
    assert [item["action"] for item in filtered.json()["items"]] == ["HIDE_REVIEW"]
    me = admin_client.get(f"{API}/users/me").json()
    assert admin_client.get(f"{API}/admin/moderation-actions", params={"admin_id": me["id"]}).json()["total"] == 2


def test_every_admin_route_requires_admin(approved_restaurant, user_client, make_client) -> None:
    owner_client, establishment_id = approved_restaurant("a")
    client_u, _ = user_client("u")
    review = post_review(client_u, establishment_id, comment="Hola")
    anonymous = make_client()
    calls = [
        ("get", "/admin/dashboard", None),
        ("get", "/admin/reviews", None),
        ("post", f"/admin/reviews/{review['id']}/block-comment", {"category": "OTHER"}),
        ("post", f"/admin/reviews/{review['id']}/unblock-comment", None),
        ("post", f"/admin/reviews/{review['id']}/hide", {"category": "OTHER"}),
        ("post", f"/admin/reviews/{review['id']}/restore", None),
        ("delete", f"/admin/reviews/{review['id']}?reason=Motivo+largo", None),
        ("post", "/admin/review-replies/1/block", {"category": "OTHER"}),
        ("delete", "/admin/review-images/1?reason=Motivo+largo", None),
        ("get", "/admin/reports", None),
        ("post", "/admin/reports/1/resolve", {"action": "NONE"}),
        ("post", "/admin/reports/1/dismiss", None),
        ("get", "/admin/moderation-actions", None),
        ("post", f"/admin/establishments/{establishment_id}/suspend", {"reason": REASON}),
        ("post", f"/admin/establishments/{establishment_id}/reactivate", None),
        ("patch", f"/admin/establishments/{establishment_id}", {"name": "Hackeado"}),
        ("put", f"/admin/establishments/{establishment_id}/schedules", []),
    ]
    for client, expected in [(client_u, 403), (owner_client, 403), (anonymous, 401)]:
        for method, path, body in calls:
            kwargs = {"json": body} if body is not None else {}
            response = getattr(client, method)(f"{API}{path}", **kwargs)
            assert response.status_code == expected, (method, path, response.status_code)
