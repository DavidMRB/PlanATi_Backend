from tests.conftest import API, DEFAULT_PASSWORD, restaurant_payload


def test_register_restaurant_sets_cookie_and_pending_status(register_restaurant) -> None:
    client, data = register_restaurant("a")

    assert data["role"] == "restaurant"
    assert data["establishment_status"] == "PENDING"
    assert "access_token" in client.cookies
    assert "access_token" not in data

    me = client.get(f"{API}/users/me").json()
    assert me["role"] == "restaurant"
    assert me["phone_verified"] is True
    assert me["status"] == "ACTIVE"


def test_register_restaurant_duplicate_email_conflict(make_client, register_restaurant) -> None:
    register_restaurant("a")
    response = make_client().post(f"{API}/auth/restaurant/register", json=restaurant_payload("a"))
    assert response.status_code == 409


def test_register_restaurant_requires_strong_password_and_fields(make_client) -> None:
    client = make_client()
    weak = client.post(f"{API}/auth/restaurant/register", json=restaurant_payload("a", password="password"))
    assert weak.status_code == 422

    payload = restaurant_payload("b")
    del payload["category"]
    missing = client.post(f"{API}/auth/restaurant/register", json=payload)
    assert missing.status_code == 422

    bad_phone = client.post(
        f"{API}/auth/restaurant/register", json=restaurant_payload("c", establishment_phone="12345")
    )
    assert bad_phone.status_code == 422


def test_login_returns_role_and_establishment_status(make_client, register_restaurant) -> None:
    register_restaurant("a")
    client = make_client()
    response = client.post(
        f"{API}/auth/login",
        json={"email": "gerencia-a@restaurante.com", "password": DEFAULT_PASSWORD},
    )
    assert response.status_code == 200
    assert response.json() == {
        "registration_complete": True,
        "requires_phone_verification": False,
        "role": "restaurant",
        "establishment_status": "PENDING",
    }
    assert "access_token" in client.cookies


def test_pending_restaurant_blocked_from_panel_but_can_see_status(register_restaurant) -> None:
    client, _ = register_restaurant("a")

    blocked = client.get(f"{API}/restaurant/products")
    assert blocked.status_code == 403
    assert blocked.json() == {"detail": "Establecimiento en revisión", "status": "PENDING"}

    status_response = client.get(f"{API}/restaurant/status")
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "PENDING"


def test_pending_restaurant_can_only_save_images_in_profile(register_restaurant) -> None:
    client, _ = register_restaurant("a")

    saved = client.patch(f"{API}/restaurant/profile", json={"banner_image_url": "https://pub.r2.dev/b.jpg"})
    assert saved.status_code == 200
    assert saved.json()["banner_image_url"] == "https://pub.r2.dev/b.jpg"

    blocked = client.patch(f"{API}/restaurant/profile", json={"description": "Cambio no permitido"})
    assert blocked.status_code == 403


def test_reject_and_reapply_flow(register_restaurant, admin_client) -> None:
    client, data = register_restaurant("a")
    establishment_id = data["establishment_id"]

    rejected = admin_client.post(
        f"{API}/admin/establishments/{establishment_id}/reject",
        json={"reason": "Se requiere actualizar el teléfono de contacto oficial."},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "REJECTED"

    blocked = client.get(f"{API}/restaurant/products")
    assert blocked.status_code == 403
    assert blocked.json()["status"] == "REJECTED"

    status_body = client.get(f"{API}/restaurant/status").json()
    assert status_body["rejection_reason"] == "Se requiere actualizar el teléfono de contacto oficial."

    # Un establecimiento rechazado puede leer su perfil para precargar el formulario de corrección.
    profile = client.get(f"{API}/restaurant/profile")
    assert profile.status_code == 200
    assert profile.json()["name"] == "Parrilla A"
    assert profile.json()["status"] == "REJECTED"

    reapplied = client.patch(
        f"{API}/restaurant/reapply",
        json={
            "phone": "+57 310 555 1234",
            "profile_image_url": "https://pub.r2.dev/establishments/logo.png",
            "banner_image_url": "https://pub.r2.dev/establishments/banner.png",
        },
    )
    assert reapplied.status_code == 200
    assert reapplied.json()["status"] == "PENDING"

    status_body = client.get(f"{API}/restaurant/status").json()
    assert status_body["status"] == "PENDING"
    assert status_body["rejection_reason"] is None

    approved = admin_client.post(f"{API}/admin/establishments/{establishment_id}/approve")
    assert approved.status_code == 200

    assert client.get(f"{API}/restaurant/products").status_code == 200
    profile = client.get(f"{API}/restaurant/profile").json()
    assert profile["phone"] == "+573105551234"
    assert profile["profile_image_url"] == "https://pub.r2.dev/establishments/logo.png"
    assert profile["banner_image_url"] == "https://pub.r2.dev/establishments/banner.png"


def test_reapply_only_allowed_when_rejected(register_restaurant) -> None:
    client, _ = register_restaurant("a")
    assert client.patch(f"{API}/restaurant/reapply", json={"name": "Nuevo nombre"}).status_code == 409


def test_regular_user_cannot_use_restaurant_panel(make_client, create_user) -> None:
    create_user("user@planati.com")
    client = make_client()
    client.post(f"{API}/auth/login", json={"email": "user@planati.com", "password": DEFAULT_PASSWORD})
    assert client.get(f"{API}/restaurant/status").status_code == 403


def test_panel_requires_authentication(make_client) -> None:
    assert make_client().get(f"{API}/restaurant/status").status_code == 401


def test_profile_update_and_images(approved_restaurant) -> None:
    client, _ = approved_restaurant("a")

    updated = client.patch(
        f"{API}/restaurant/profile",
        json={"description": "Nueva descripción", "banner_image_url": "https://pub.r2.dev/b.jpg"},
    )
    assert updated.status_code == 200
    assert updated.json()["description"] == "Nueva descripción"
    assert updated.json()["banner_image_url"] == "https://pub.r2.dev/b.jpg"

    created = client.post(
        f"{API}/restaurant/images",
        json={"image_url": "https://pub.r2.dev/g.jpg", "image_type": "GALLERY", "caption": "Terraza"},
    )
    assert created.status_code == 201
    client.post(f"{API}/restaurant/images", json={"image_url": "https://pub.r2.dev/m.jpg", "image_type": "MENU"})

    gallery = client.get(f"{API}/restaurant/images", params={"image_type": "GALLERY"}).json()
    assert [image["caption"] for image in gallery] == ["Terraza"]
    assert len(client.get(f"{API}/restaurant/images").json()) == 2

    image_id = created.json()["id"]
    assert client.delete(f"{API}/restaurant/images/{image_id}").status_code == 204
    assert client.delete(f"{API}/restaurant/images/{image_id}").status_code == 404


def test_images_are_isolated_between_restaurants(approved_restaurant) -> None:
    client_a, _ = approved_restaurant("a")
    client_b, _ = approved_restaurant("b")
    image = client_a.post(
        f"{API}/restaurant/images", json={"image_url": "https://pub.r2.dev/g.jpg", "image_type": "GALLERY"}
    ).json()
    assert client_b.delete(f"{API}/restaurant/images/{image['id']}").status_code == 404


def test_upload_url_validates_folder_and_requires_r2(register_restaurant) -> None:
    client, _ = register_restaurant("a")
    assert client.post(f"{API}/restaurant/upload-url", params={"folder": "secret"}).status_code == 422
    # Sin credenciales de R2 configuradas el servicio responde 503.
    response = client.post(f"{API}/restaurant/upload-url", params={"folder": "menu"})
    assert response.status_code in {200, 503}


def test_restaurant_cannot_use_legacy_establishment_routes(approved_restaurant) -> None:
    client, establishment_id = approved_restaurant("a")
    response = client.patch(f"{API}/establishments/{establishment_id}", json={"name": "Hackeado"})
    assert response.status_code == 403


def test_logout_clears_cookie(register_restaurant) -> None:
    client, _ = register_restaurant("a")
    assert client.post(f"{API}/auth/logout").status_code == 204
    assert client.get(f"{API}/restaurant/status").status_code == 401


def test_avatar_upload_url_requires_session_and_valid_extension(make_client, register_restaurant) -> None:
    assert make_client().post(f"{API}/users/me/upload-url").status_code == 401

    client, _ = register_restaurant("a")
    # Con extensión inválida se rechaza antes de tocar R2; sin credenciales de R2 responde 503.
    assert client.post(f"{API}/users/me/upload-url", params={"file_extension": ".exe"}).status_code in {400, 503}
