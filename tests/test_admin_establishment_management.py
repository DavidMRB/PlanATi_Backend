"""B5: suspender/reactivar establecimientos y editarlos "como el establecimiento" desde la consola admin."""

from tests.conftest import API, CUCUTA_LAT, CUCUTA_LNG
from tests.moderation_helpers import REASON, actions, notification_types, post_review

VIEWPORT = {"north": CUCUTA_LAT + 0.05, "south": CUCUTA_LAT - 0.05, "east": CUCUTA_LNG + 0.05, "west": CUCUTA_LNG - 0.05}


def test_suspend_removes_from_directory_map_and_reviews(
    admin_client, approved_restaurant, user_client, make_client
) -> None:
    owner_client, establishment_id = approved_restaurant("a")
    reviewer, _ = user_client("u")
    post_review(reviewer, establishment_id, comment="Rico")
    anonymous = make_client()
    assert [item["id"] for item in anonymous.get(f"{API}/establishments").json()] == [establishment_id]

    response = admin_client.post(f"{API}/admin/establishments/{establishment_id}/suspend", json={"reason": REASON})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "SUSPENDED" and response.json()["suspension_reason"] == REASON

    assert anonymous.get(f"{API}/establishments").json() == []
    assert anonymous.get(f"{API}/establishments/map", params=VIEWPORT).json()["items"] == []
    nearby = anonymous.get(f"{API}/establishments/nearby", params={"latitude": CUCUTA_LAT, "longitude": CUCUTA_LNG})
    assert nearby.json() == []
    assert anonymous.get(f"{API}/establishments/{establishment_id}").status_code == 404
    assert anonymous.get(f"{API}/reviews/establishments/{establishment_id}").status_code == 404
    other, _ = user_client("v")
    assert other.post(f"{API}/reviews/establishments/{establishment_id}", json={"rating": 5}).status_code == 404

    # El panel queda cerrado (403 con el estado) salvo /restaurant/status, que muestra el motivo.
    panel = owner_client.get(f"{API}/restaurant/products")
    assert panel.status_code == 403 and panel.json() == {"detail": "Establecimiento suspendido", "status": "SUSPENDED"}
    assert owner_client.patch(f"{API}/restaurant/profile", json={"profile_image_url": "https://x.com/a.jpg"}).status_code == 403
    status_body = owner_client.get(f"{API}/restaurant/status").json()
    assert status_body["status"] == "SUSPENDED" and status_body["suspension_reason"] == REASON
    # Suspender no es rechazar: no puede re-aplicar.
    assert owner_client.patch(f"{API}/restaurant/reapply", json={"name": "Otro nombre"}).status_code == 409
    assert "ESTABLISHMENT_SUSPENDED" in notification_types(owner_client)

    # El dueño y el admin aún pueden previsualizar la ficha.
    assert admin_client.get(f"{API}/establishments/{establishment_id}").status_code == 200

    listed = admin_client.get(f"{API}/admin/establishments", params={"status": "SUSPENDED"}).json()
    assert [item["id"] for item in listed] == [establishment_id]
    assert listed[0]["suspension_reason"] == REASON
    assert admin_client.get(f"{API}/admin/dashboard").json()["suspended_establishments"] == 1

    assert admin_client.post(f"{API}/admin/establishments/{establishment_id}/suspend", json={"reason": REASON}).status_code == 409
    assert admin_client.post(f"{API}/admin/establishments/{establishment_id}/approve").status_code == 409

    reactivated = admin_client.post(f"{API}/admin/establishments/{establishment_id}/reactivate")
    assert reactivated.status_code == 200 and reactivated.json()["status"] == "APPROVED"
    assert [item["id"] for item in anonymous.get(f"{API}/establishments").json()] == [establishment_id]
    assert owner_client.get(f"{API}/restaurant/products").status_code == 200
    assert notification_types(owner_client)[0] == "ESTABLISHMENT_REACTIVATED"
    assert admin_client.post(f"{API}/admin/establishments/{establishment_id}/reactivate").status_code == 409


def test_only_approved_can_be_suspended(admin_client, register_restaurant) -> None:
    _, data = register_restaurant("a")
    response = admin_client.post(f"{API}/admin/establishments/{data['establishment_id']}/suspend", json={"reason": REASON})
    assert response.status_code == 409
    assert admin_client.post(f"{API}/admin/establishments/9999/suspend", json={"reason": REASON}).status_code == 404
    assert admin_client.post(f"{API}/admin/establishments/{data['establishment_id']}/suspend", json={}).status_code == 422


def test_suspension_and_reactivation_are_logged(admin_client, approved_restaurant, db_session) -> None:
    _, establishment_id = approved_restaurant("a")
    admin_client.post(f"{API}/admin/establishments/{establishment_id}/suspend", json={"reason": REASON})
    admin_client.post(f"{API}/admin/establishments/{establishment_id}/reactivate", json={"note": "Corrigió la información"})
    entries = actions(db_session, target_type="ESTABLISHMENT", target_id=establishment_id)
    assert [(entry.action, entry.reason) for entry in entries] == [
        ("SUSPEND_ESTABLISHMENT", REASON),
        ("REACTIVATE_ESTABLISHMENT", "Corrigió la información"),
    ]
    log = admin_client.get(f"{API}/admin/moderation-actions", params={"target_type": "ESTABLISHMENT"}).json()
    assert log["total"] == 2
    assert log["items"][0]["action"] == "REACTIVATE_ESTABLISHMENT"
    assert log["items"][0]["admin_email"] == "admin@planati.com"


def test_admin_edits_profile_as_the_establishment(admin_client, approved_restaurant, db_session) -> None:
    owner_client, establishment_id = approved_restaurant("a")
    response = admin_client.patch(
        f"{API}/admin/establishments/{establishment_id}",
        json={"name": "Parrilla Renovada", "establishment_type": "BAR", "reason": "Nombre con publicidad"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Parrilla Renovada"
    assert response.json()["establishment_type"] == "BAR"
    assert owner_client.get(f"{API}/restaurant/profile").json()["name"] == "Parrilla Renovada"

    [entry] = actions(db_session, action="EDIT_ESTABLISHMENT")
    assert entry.reason == "Nombre con publicidad"
    assert entry.details == {
        "name": {"before": "Parrilla A", "after": "Parrilla Renovada"},
        "establishment_type": {"before": "RESTAURANT", "after": "BAR"},
    }
    [notice] = [n for n in owner_client.get(f"{API}/notifications").json()["items"] if n["type"] == "ESTABLISHMENT_EDITED_BY_ADMIN"]
    assert "Nombre con publicidad" in notice["body"]

    # Sin cambios reales no hay bitácora ni aviso.
    admin_client.patch(f"{API}/admin/establishments/{establishment_id}", json={"name": "Parrilla Renovada"})
    assert len(actions(db_session, action="EDIT_ESTABLISHMENT")) == 1

    out_of_area = admin_client.patch(
        f"{API}/admin/establishments/{establishment_id}", json={"latitude": "40.0", "longitude": "-3.7"}
    )
    assert out_of_area.status_code == 400
    assert admin_client.patch(f"{API}/admin/establishments/9999", json={"name": "Nada"}).status_code == 404


def test_admin_manages_catalog_with_log_and_daily_notice(admin_client, approved_restaurant, db_session) -> None:
    owner_client, establishment_id = approved_restaurant("a")
    base = f"{API}/admin/establishments/{establishment_id}"

    product = admin_client.post(f"{base}/products", json={"name": "Picada", "price": "25000"})
    assert product.status_code == 201, product.text
    product_id = product.json()["id"]
    assert admin_client.patch(f"{base}/products/{product_id}", json={"price": "27000"}).json()["price"] == "27000.00"
    combo = admin_client.post(f"{base}/combos", json={"name": "Combo", "price": "30000", "items": [{"product_id": product_id}]})
    assert combo.status_code == 201
    image = admin_client.post(f"{base}/images", json={"image_url": "https://pub.r2.dev/g.jpg", "image_type": "GALLERY"})
    assert image.status_code == 201
    schedules = admin_client.put(f"{base}/schedules", json=[{"day_of_week": 0, "opening_time": "08:00", "closing_time": "15:00"}])
    assert schedules.status_code == 200
    assert len(admin_client.get(f"{base}/schedules").json()) == 1

    # El dueño ve los cambios en su panel.
    assert {item["name"] for item in owner_client.get(f"{API}/restaurant/products").json()} == {"Picada", "Combo"}

    # Una operación rechazada no deja rastro en la bitácora.
    invalid = admin_client.post(f"{base}/combos", json={"name": "Malo", "price": "1", "items": [{"product_id": 9999}]})
    assert invalid.status_code == 400
    assert admin_client.delete(f"{base}/products/{product_id}").status_code == 409  # está en un combo
    assert admin_client.delete(f"{base}/images/9999").status_code == 404
    overlap = admin_client.put(
        f"{base}/schedules",
        json=[
            {"day_of_week": 0, "opening_time": "08:00", "closing_time": "15:00"},
            {"day_of_week": 0, "opening_time": "14:00", "closing_time": "18:00"},
        ],
    )
    assert overlap.status_code == 400

    entries = actions(db_session, action="EDIT_CATALOG")
    assert [entry.details["operation"] for entry in entries] == [
        "create_product",
        "update_product",
        "create_combo",
        "add_image",
        "replace_schedules",
    ]
    assert entries[1].details["item_id"] == product_id and entries[1].details["data"] == {"price": "27000"}
    # Un solo aviso al día aunque haya varias ediciones.
    assert notification_types(owner_client).count("ESTABLISHMENT_EDITED_BY_ADMIN") == 1

    # El catálogo del dueño (sin auditoría) sigue funcionando igual.
    assert owner_client.post(f"{API}/restaurant/products", json={"name": "Jugo", "price": "5000"}).status_code == 201
    assert len(actions(db_session, action="EDIT_CATALOG")) == 5


def test_admin_catalog_routes(admin_client, approved_restaurant, register_restaurant, user_client) -> None:
    _, establishment_id = approved_restaurant("a")
    _, pending = register_restaurant("p")
    # El admin gestiona cualquier local, también uno pendiente.
    assert admin_client.get(f"{API}/admin/establishments/{pending['establishment_id']}/products").json() == []
    assert admin_client.get(f"{API}/admin/establishments/9999/products").status_code == 404
    client_a, _ = user_client("u")
    assert client_a.get(f"{API}/admin/establishments/{establishment_id}/products").status_code == 403
    assert client_a.post(f"{API}/admin/establishments/{establishment_id}/products", json={"name": "X", "price": "1"}).status_code == 403


def test_admin_establishment_list_and_detail_fields(admin_client, approved_restaurant, add_reviews) -> None:
    _, establishment_id = approved_restaurant("a")
    add_reviews(establishment_id, [5, 4])
    [item] = admin_client.get(f"{API}/admin/establishments").json()
    assert item["rating_count"] == 2 and item["rating_avg"] == 4.5
    assert item["has_location"] is True and item["open_reports_count"] == 0
    assert item["establishment_type"] == "RESTAURANT"
    body = admin_client.get(f"{API}/admin/establishments/{establishment_id}").json()
    assert body["latitude"] is not None and body["location_source"] == "MAP_PIN"


def test_dashboard_has_moderation_counters(admin_client, approved_restaurant, register_restaurant) -> None:
    approved_restaurant("a")
    register_restaurant("p")
    body = admin_client.get(f"{API}/admin/dashboard").json()
    assert body["users_count"] == 3 and body["establishments_count"] == 2 and body["reviews_count"] == 0
    assert body["pending_establishments"] == 1
    for key in (
        "suspended_establishments",
        "suspended_users",
        "open_reports",
        "hidden_reviews",
        "blocked_comments",
        "flagged_for_review",
        "reviews_last_7_days",
        "scheduled_plans",
        "establishments_without_location",
    ):
        assert body[key] == 0, key
