from tests.conftest import API, DEFAULT_PASSWORD


def test_admin_lists_and_filters_establishments(register_restaurant, admin_client) -> None:
    _, first = register_restaurant("a")
    register_restaurant("b")
    admin_client.post(f"{API}/admin/establishments/{first['establishment_id']}/approve")

    all_items = admin_client.get(f"{API}/admin/establishments").json()
    assert len(all_items) == 2
    assert {item["owner_email"] for item in all_items} == {
        "gerencia-a@restaurante.com",
        "gerencia-b@restaurante.com",
    }

    pending = admin_client.get(f"{API}/admin/establishments", params={"status": "PENDING"}).json()
    assert [item["name"] for item in pending] == ["Parrilla B"]

    searched = admin_client.get(f"{API}/admin/establishments", params={"search": "Parrilla A"}).json()
    assert [item["id"] for item in searched] == [first["establishment_id"]]

    paged = admin_client.get(f"{API}/admin/establishments", params={"limit": 1}).json()
    assert len(paged) == 1

    assert admin_client.get(f"{API}/admin/establishments", params={"status": "OTRO"}).status_code == 422


def test_admin_detail(register_restaurant, admin_client) -> None:
    _, data = register_restaurant("a", profile_image_url="https://pub.r2.dev/logo.jpg")
    detail = admin_client.get(f"{API}/admin/establishments/{data['establishment_id']}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["profile_image_url"] == "https://pub.r2.dev/logo.jpg"
    assert body["manager_name"] == "Carlos Gómez"
    assert body["owner_email"] == "gerencia-a@restaurante.com"
    assert admin_client.get(f"{API}/admin/establishments/9999").status_code == 404


def test_incompatible_transitions_return_conflict(register_restaurant, admin_client) -> None:
    _, data = register_restaurant("a")
    establishment_id = data["establishment_id"]
    reason = {"reason": "Datos de contacto no verificables."}

    assert admin_client.post(f"{API}/admin/establishments/{establishment_id}/approve").status_code == 200
    assert admin_client.post(f"{API}/admin/establishments/{establishment_id}/approve").status_code == 409

    # Suspensión administrativa: APPROVED -> REJECTED.
    assert admin_client.post(f"{API}/admin/establishments/{establishment_id}/reject", json=reason).status_code == 200
    assert admin_client.post(f"{API}/admin/establishments/{establishment_id}/reject", json=reason).status_code == 409
    # Un rechazado debe re-aplicar antes de volver a ser aprobado.
    assert admin_client.post(f"{API}/admin/establishments/{establishment_id}/approve").status_code == 409

    assert admin_client.post(f"{API}/admin/establishments/9999/approve").status_code == 404


def test_admin_routes_forbidden_for_non_admins(make_client, create_user, register_restaurant) -> None:
    restaurant_client, data = register_restaurant("a")
    assert restaurant_client.get(f"{API}/admin/establishments").status_code == 403
    assert (
        restaurant_client.post(f"{API}/admin/establishments/{data['establishment_id']}/approve").status_code
        == 403
    )

    create_user("user@planati.com")
    user_client = make_client()
    user_client.post(f"{API}/auth/login", json={"email": "user@planati.com", "password": DEFAULT_PASSWORD})
    assert user_client.get(f"{API}/admin/establishments").status_code == 403


def test_public_directory_only_shows_approved(make_client, register_restaurant, admin_client) -> None:
    owner_client, pending = register_restaurant("a")
    _, approved = register_restaurant("b")
    admin_client.post(f"{API}/admin/establishments/{approved['establishment_id']}/approve")

    anonymous = make_client()
    listed = anonymous.get(f"{API}/establishments").json()
    assert [item["id"] for item in listed] == [approved["establishment_id"]]

    assert anonymous.get(f"{API}/establishments/{pending['establishment_id']}").status_code == 404
    assert anonymous.get(f"{API}/establishments/{approved['establishment_id']}").status_code == 200

    # El propietario y el administrador sí pueden previsualizar la ficha pendiente.
    assert owner_client.get(f"{API}/establishments/{pending['establishment_id']}").status_code == 200
    assert admin_client.get(f"{API}/establishments/{pending['establishment_id']}").status_code == 200
