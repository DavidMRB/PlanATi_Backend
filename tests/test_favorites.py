"""B7: favoritos (idempotentes, solo aprobados, aislados por usuario) e `is_favorite` en el detalle."""

import asyncio

from sqlalchemy import func, select

from app.models.favorite import Favorite
from tests.conftest import API, login
from tests.moderation_helpers import REASON


def _count_favorites(db_session) -> int:
    async def scenario() -> int:
        async with db_session() as session:
            return await session.scalar(select(func.count()).select_from(Favorite))

    return asyncio.run(scenario())


def test_put_is_idempotent_and_detail_shows_is_favorite(user_client, approved_restaurant, make_client, db_session):
    _, establishment_id = approved_restaurant("a")
    client, _ = user_client("a")

    assert client.get(f"{API}/establishments/{establishment_id}").json()["is_favorite"] is False
    for _ in range(2):
        response = client.put(f"{API}/favorites/{establishment_id}")
        assert response.status_code == 204 and response.content == b""
    assert _count_favorites(db_session) == 1
    assert client.get(f"{API}/establishments/{establishment_id}").json()["is_favorite"] is True

    page = client.get(f"{API}/favorites").json()
    assert page["total"] == 1 and page["skip"] == 0 and page["limit"] == 20
    item = page["items"][0]
    assert item["id"] == establishment_id and "reviews" not in item and "rating_avg" in item
    assert client.get(f"{API}/favorites/ids").json() == {"establishment_ids": [establishment_id]}

    # Sin sesión: false.
    assert make_client().get(f"{API}/establishments/{establishment_id}").json()["is_favorite"] is False

    for _ in range(2):
        assert client.delete(f"{API}/favorites/{establishment_id}").status_code == 204
    assert client.get(f"{API}/favorites").json()["total"] == 0
    assert client.get(f"{API}/establishments/{establishment_id}").json()["is_favorite"] is False


def test_only_approved_establishments(user_client, register_restaurant, approved_restaurant, admin_client):
    _, pending = register_restaurant("p")
    _, establishment_id = approved_restaurant("a")
    client, _ = user_client("a")

    assert client.put(f"{API}/favorites/{pending['establishment_id']}").status_code == 404
    missing = client.put(f"{API}/favorites/999999")
    assert missing.status_code == 404 and missing.json()["detail"] == "Establecimiento no encontrado"

    # Un favorito suspendido deja de listarse, pero vuelve al reactivar el local.
    assert client.put(f"{API}/favorites/{establishment_id}").status_code == 204
    suspend = admin_client.post(f"{API}/admin/establishments/{establishment_id}/suspend", json={"reason": REASON})
    assert suspend.status_code == 200
    assert client.get(f"{API}/favorites").json() == {"items": [], "total": 0, "skip": 0, "limit": 20}
    assert client.get(f"{API}/favorites/ids").json() == {"establishment_ids": []}
    assert client.put(f"{API}/favorites/{establishment_id}").status_code == 404
    assert client.delete(f"{API}/favorites/{establishment_id}").status_code == 204  # quitarlo sí se puede
    assert admin_client.post(f"{API}/admin/establishments/{establishment_id}/reactivate").status_code == 200
    assert client.get(f"{API}/favorites").json()["total"] == 0  # se había quitado

    assert client.put(f"{API}/favorites/{establishment_id}").status_code == 204
    assert client.get(f"{API}/favorites").json()["total"] == 1


def test_isolation_between_users(user_client, approved_restaurant):
    _, first = approved_restaurant("a")
    _, second = approved_restaurant("b")
    ana, _ = user_client("a")
    beto, _ = user_client("b")

    assert ana.put(f"{API}/favorites/{first}").status_code == 204
    assert beto.put(f"{API}/favorites/{second}").status_code == 204
    assert ana.get(f"{API}/favorites/ids").json() == {"establishment_ids": [first]}
    assert beto.get(f"{API}/favorites/ids").json() == {"establishment_ids": [second]}
    assert beto.get(f"{API}/establishments/{first}").json()["is_favorite"] is False

    # Borrar el favorito de otro usuario no lo toca.
    assert beto.delete(f"{API}/favorites/{first}").status_code == 204
    assert ana.get(f"{API}/favorites/ids").json() == {"establishment_ids": [first]}


def test_ordering_and_pagination(user_client, approved_restaurant):
    ids = [approved_restaurant(suffix)[1] for suffix in ("a", "b", "c")]
    client, _ = user_client("a")
    for establishment_id in ids:
        assert client.put(f"{API}/favorites/{establishment_id}").status_code == 204

    newest_first = list(reversed(ids))
    assert client.get(f"{API}/favorites/ids").json()["establishment_ids"] == newest_first
    page = client.get(f"{API}/favorites", params={"skip": 1, "limit": 1}).json()
    assert page["total"] == 3 and [item["id"] for item in page["items"]] == [newest_first[1]]
    assert client.get(f"{API}/favorites", params={"limit": 51}).status_code == 422


def test_only_active_user_accounts(make_client, create_user, approved_restaurant, admin_client):
    restaurant_client, establishment_id = approved_restaurant("a")

    anonymous = make_client()
    assert anonymous.get(f"{API}/favorites").status_code == 401
    assert anonymous.put(f"{API}/favorites/{establishment_id}").status_code == 401

    for client in (restaurant_client, admin_client):
        response = client.put(f"{API}/favorites/{establishment_id}")
        assert response.status_code == 403 and response.json()["code"] == "ROLE_NOT_ALLOWED"
        assert client.get(f"{API}/establishments/{establishment_id}").json()["is_favorite"] is False

    create_user("pendiente@planati.com", phone_verified=False, status="PENDING_PHONE")
    pending = make_client()
    login(pending, "pendiente@planati.com")
    response = pending.get(f"{API}/favorites")
    assert response.status_code == 403 and response.json()["code"] == "PHONE_NOT_VERIFIED"


def test_writes_require_csrf_token(user_client, approved_restaurant):
    _, establishment_id = approved_restaurant("a")
    client, _ = user_client("a")
    client.headers.pop("X-CSRF-Token")
    response = client.put(f"{API}/favorites/{establishment_id}")
    assert response.status_code == 403 and response.json()["code"] == "CSRF_FAILED"

