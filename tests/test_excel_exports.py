from io import BytesIO

from openpyxl import load_workbook

from app.models.review import BLOCKED_COMMENT_NOTICE, Review
from app.services.excel_service import XLSX_MEDIA_TYPE
from tests.conftest import API
from tests.test_catalog_combos import _create_product
from tests.test_review_replies import reply, review, update_rows


def workbook_from(response):
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == XLSX_MEDIA_TYPE
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["cache-control"] == "private, no-store"
    return load_workbook(BytesIO(response.content))


def test_menu_export_includes_own_products_and_combo_components(approved_restaurant, register_restaurant):
    owner, local_id = approved_restaurant("a")
    other, _ = approved_restaurant("b")
    pending, _ = register_restaurant("p")
    product = _create_product(owner, "=1+1")
    _create_product(other, "Producto ajeno")
    assert owner.post(
        f"{API}/restaurant/combos",
        json={"name": "Combo de prueba", "price": 49000, "items": [{"product_id": product["id"], "quantity": 2}]},
    ).status_code == 201
    assert owner.post(
        f"{API}/restaurant/images",
        json={"image_url": "https://pub.r2.dev/menu.jpg", "image_type": "MENU"},
    ).status_code == 201
    url = f"{API}/restaurant/exports/menu.xlsx"
    assert pending.get(url).status_code == 403

    response = owner.get(url)
    book = workbook_from(response)
    assert f"menu-establecimiento-{local_id}.xlsx" in response.headers["content-disposition"]
    assert book.sheetnames == ["Productos", "Combos", "Composición", "Menú físico"]
    products = book["Productos"]
    assert products.max_row == 3
    assert products["B3"].value == "=1+1" and products["B3"].data_type == "s"
    assert products["D3"].value == 24000 and products["D3"].data_type == "n"
    assert products.freeze_panes == "A3" and products.auto_filter.ref == "A2:F3"
    assert book["Composición"]["E3"].value == 2
    assert book["Menú físico"]["C3"].value == "https://pub.r2.dev/menu.jpg"


def test_reviews_export_uses_same_visibility_as_owner_panel(approved_restaurant, user_client, db_session):
    owner, local_id = approved_restaurant("a")
    other, _ = approved_restaurant("b")
    blocked_author, _ = user_client("u1")
    hidden_author, _ = user_client("u2")
    blocked_id = review(blocked_author, local_id, comment="Texto original bloqueado")
    hidden_id = review(hidden_author, local_id, comment="Texto de reseña oculta")
    update_rows(db_session, Review, blocked_id, comment_status="BLOCKED", moderation_category="OFFENSIVE_LANGUAGE")
    update_rows(db_session, Review, hidden_id, status="HIDDEN")
    assert reply(owner, blocked_id, "Gracias por la calificación").status_code == 200

    url = f"{API}/restaurant/exports/reviews.xlsx"
    sheet = workbook_from(owner.get(url))["Reseñas"]
    assert sheet.max_row == 3
    assert sheet["A3"].value == blocked_id
    assert sheet["D3"].value == BLOCKED_COMMENT_NOTICE
    assert sheet["E3"].is_date
    assert sheet["G3"].value == "Gracias por la calificación"
    assert workbook_from(other.get(url))["Reseñas"].max_row == 2
    assert blocked_author.get(url).status_code == 403


def test_establishment_export_is_admin_only_and_respects_filters(approved_restaurant, register_restaurant, admin_client):
    owner, local_id = approved_restaurant("a")
    register_restaurant("b")
    url = f"{API}/admin/exports/establishments.xlsx"
    assert owner.get(url).status_code == 403

    all_rows = workbook_from(admin_client.get(url))["Establecimientos"]
    assert all_rows.max_row == 4
    filtered = workbook_from(admin_client.get(url, params={"status": "APPROVED", "search": "Parrilla A"}))["Establecimientos"]
    assert filtered.max_row == 3
    assert filtered["A3"].value == local_id
    assert filtered["E3"].value == "Aprobado"
    assert filtered["L3"].value == "gerencia-a@restaurante.com"
    assert filtered["M3"].is_date


def test_admin_exports_menu_and_reviews_for_the_selected_establishment(approved_restaurant, admin_client, user_client):
    owner, first_id = approved_restaurant("a")
    other, second_id = approved_restaurant("b")
    author, _ = user_client("a")
    _create_product(owner, "Menú del primero")
    _create_product(other, "Menú del segundo")
    review_id = review(author, first_id, comment="Reseña del primero")

    first = f"{API}/admin/establishments/{first_id}/exports"
    second = f"{API}/admin/establishments/{second_id}/exports"
    for filename in ("menu.xlsx", "reviews.xlsx"):
        assert owner.get(f"{first}/{filename}").status_code == 403
        assert admin_client.get(f"{API}/admin/establishments/9999/exports/{filename}").status_code == 404

    assert workbook_from(admin_client.get(f"{first}/menu.xlsx"))["Productos"]["B3"].value == "Menú del primero"
    assert workbook_from(admin_client.get(f"{second}/menu.xlsx"))["Productos"]["B3"].value == "Menú del segundo"
    assert workbook_from(admin_client.get(f"{first}/reviews.xlsx"))["Reseñas"]["A3"].value == review_id
    assert workbook_from(admin_client.get(f"{second}/reviews.xlsx"))["Reseñas"].max_row == 2
