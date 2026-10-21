from fastapi.testclient import TestClient

from tests.conftest import API


def _create_product(client: TestClient, name: str = "Hamburguesa Clásica", price: float = 24000) -> dict:
    response = client.post(
        f"{API}/restaurant/products",
        json={"name": name, "description": "Carne 150g", "price": price},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_product_crud(approved_restaurant) -> None:
    client, _ = approved_restaurant("a")
    product = _create_product(client)
    assert product["is_combo"] is False
    assert product["is_available"] is True

    updated = client.patch(f"{API}/restaurant/products/{product['id']}", json={"price": 26000, "is_available": False})
    assert updated.status_code == 200
    assert float(updated.json()["price"]) == 26000
    assert updated.json()["is_available"] is False

    assert len(client.get(f"{API}/restaurant/products").json()) == 1
    assert client.delete(f"{API}/restaurant/products/{product['id']}").status_code == 204
    assert client.get(f"{API}/restaurant/products").json() == []


def test_standalone_and_composite_combos(approved_restaurant) -> None:
    client, _ = approved_restaurant("a")
    burger = _create_product(client)
    fries = _create_product(client, "Papas", 8000)

    standalone = client.post(
        f"{API}/restaurant/combos",
        json={"name": "Combo del día", "price": 30000, "items": []},
    )
    assert standalone.status_code == 201
    assert standalone.json()["is_combo"] is True
    assert standalone.json()["combo_items"] == []

    composite = client.post(
        f"{API}/restaurant/combos",
        json={
            "name": "Combo Familiar",
            "price": 55000,
            "items": [{"product_id": burger["id"], "quantity": 2}, {"product_id": fries["id"]}],
        },
    )
    assert composite.status_code == 201
    items = {item["product_id"]: item for item in composite.json()["combo_items"]}
    assert items[burger["id"]]["quantity"] == 2
    assert items[burger["id"]]["product_name"] == "Hamburguesa Clásica"
    assert items[fries["id"]]["quantity"] == 1

    combo_id = composite.json()["id"]
    updated = client.patch(
        f"{API}/restaurant/combos/{combo_id}",
        json={"price": 50000, "items": [{"product_id": fries["id"], "quantity": 3}]},
    )
    assert updated.status_code == 200
    assert [(i["product_id"], i["quantity"]) for i in updated.json()["combo_items"]] == [(fries["id"], 3)]

    # Sin "items" la composición se conserva.
    renamed = client.patch(f"{API}/restaurant/combos/{combo_id}", json={"name": "Combo Familiar XL"})
    assert len(renamed.json()["combo_items"]) == 1

    assert client.delete(f"{API}/restaurant/combos/{combo_id}").status_code == 204
    # Al eliminar el combo, el producto ya no está enlazado y puede borrarse.
    assert client.delete(f"{API}/restaurant/products/{fries['id']}").status_code == 204


def test_cannot_delete_product_linked_to_combo(approved_restaurant) -> None:
    client, _ = approved_restaurant("a")
    burger = _create_product(client)
    client.post(
        f"{API}/restaurant/combos",
        json={"name": "Combo Familiar", "price": 55000, "items": [{"product_id": burger["id"], "quantity": 2}]},
    )
    response = client.delete(f"{API}/restaurant/products/{burger['id']}")
    assert response.status_code == 409
    assert "Combo Familiar" in response.json()["detail"]


def test_combo_cannot_contain_combos(approved_restaurant) -> None:
    client, _ = approved_restaurant("a")
    combo = client.post(f"{API}/restaurant/combos", json={"name": "Combo base", "price": 10000}).json()
    nested = client.post(
        f"{API}/restaurant/combos",
        json={"name": "Combo anidado", "price": 20000, "items": [{"product_id": combo["id"]}]},
    )
    assert nested.status_code == 400

    self_reference = client.patch(
        f"{API}/restaurant/combos/{combo['id']}", json={"items": [{"product_id": combo["id"]}]}
    )
    assert self_reference.status_code == 400


def test_combo_with_foreign_product_rejected(approved_restaurant) -> None:
    client_a, _ = approved_restaurant("a")
    client_b, _ = approved_restaurant("b")
    foreign_product = _create_product(client_b)

    response = client_a.post(
        f"{API}/restaurant/combos",
        json={"name": "Combo robado", "price": 1000, "items": [{"product_id": foreign_product["id"]}]},
    )
    assert response.status_code == 400


def test_idor_on_products_and_combos(approved_restaurant) -> None:
    client_a, _ = approved_restaurant("a")
    client_b, _ = approved_restaurant("b")
    product_b = _create_product(client_b)
    combo_b = client_b.post(f"{API}/restaurant/combos", json={"name": "Combo B", "price": 1000}).json()

    assert client_a.patch(f"{API}/restaurant/products/{product_b['id']}", json={"price": 1}).status_code == 404
    assert client_a.delete(f"{API}/restaurant/products/{product_b['id']}").status_code == 404
    assert client_a.patch(f"{API}/restaurant/combos/{combo_b['id']}", json={"price": 1}).status_code == 404
    assert client_a.delete(f"{API}/restaurant/combos/{combo_b['id']}").status_code == 404
    assert client_a.get(f"{API}/restaurant/products").json() == []

    # Un producto no se puede tratar como combo ni viceversa.
    assert client_b.patch(f"{API}/restaurant/combos/{product_b['id']}", json={"price": 1}).status_code == 404
    assert client_b.delete(f"{API}/restaurant/products/{combo_b['id']}").status_code == 404


def test_public_detail_exposes_catalog_and_review_summary(make_client, approved_restaurant) -> None:
    client, establishment_id = approved_restaurant("a")
    burger = _create_product(client)
    hidden = _create_product(client, "Agotado", 1000)
    client.patch(f"{API}/restaurant/products/{hidden['id']}", json={"is_available": False})
    client.post(
        f"{API}/restaurant/combos",
        json={"name": "Combo Familiar", "price": 55000, "items": [{"product_id": burger["id"], "quantity": 2}]},
    )
    client.post(f"{API}/restaurant/images", json={"image_url": "https://pub.r2.dev/m.jpg", "image_type": "MENU"})

    detail = make_client().get(f"{API}/establishments/{establishment_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert [product["name"] for product in body["products"]] == ["Hamburguesa Clásica"]
    assert body["combos"][0]["combo_items"][0]["product_name"] == "Hamburguesa Clásica"
    assert len(body["menu_images"]) == 1
    assert body["gallery_images"] == []
    assert body["reviews_count"] == 0
    assert body["average_rating"] is None
