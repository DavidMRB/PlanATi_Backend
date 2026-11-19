"""B5: reportes de contenido (crear, cola del admin, resolver con acción, descartar, auto-ocultado)."""

from app.core.config import settings
from tests.conftest import API
from tests.moderation_helpers import actions, detail, notification_types, notifications, post_review


def _report(client, target_type: str, target_id: int, reason: str = "OFFENSIVE", **extra):
    return client.post(
        f"{API}/reports", json={"target_type": target_type, "target_id": target_id, "reason": reason, **extra}
    )


def _setup(approved_restaurant, user_client):
    owner_client, establishment_id = approved_restaurant("a")
    author, author_id = user_client("u")
    review = post_review(author, establishment_id, rating=1, comment="Son unos ladrones")
    return owner_client, establishment_id, author, author_id, review


def test_create_report_and_validations(approved_restaurant, user_client, admin_client, make_client, create_user) -> None:
    owner_client, establishment_id, author, _, review = _setup(approved_restaurant, user_client)
    reporter, _ = user_client("r")

    created = _report(reporter, "REVIEW", review["id"], details="  Insulta al personal  ")
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "OPEN" and created.json()["details"] == "Insulta al personal"

    duplicate = _report(reporter, "REVIEW", review["id"], reason="SPAM")
    assert duplicate.status_code == 409 and duplicate.json()["detail"] == "Ya reportaste este contenido."
    assert _report(author, "REVIEW", review["id"]).status_code == 400  # contenido propio
    assert _report(owner_client, "ESTABLISHMENT", establishment_id).status_code == 400
    # El restaurante puede reportar una reseña falsa sobre su local.
    assert _report(owner_client, "REVIEW", review["id"], reason="FALSE_INFO").status_code == 201

    assert _report(reporter, "REVIEW", 9999).status_code == 404
    assert _report(reporter, "ESTABLISHMENT", establishment_id).status_code == 201
    assert _report(reporter, "USER", reporter.get(f"{API}/users/me").json()["id"]).status_code == 400
    assert _report(reporter, "REVIEW", review["id"], reason="OTRO").status_code == 422
    assert _report(reporter, "COSA", 1).status_code == 422

    assert _report(make_client(), "REVIEW", review["id"]).status_code == 401
    create_user("pendiente@planati.com", phone_verified=False, status="PENDING_PHONE")
    pending = make_client()
    pending.post(f"{API}/auth/login", json={"email": "pendiente@planati.com", "password": "Password123!"})
    assert _report(pending, "REVIEW", review["id"]).status_code == 403


def test_cannot_report_invisible_content(approved_restaurant, register_restaurant, user_client, admin_client) -> None:
    _, _, _, _, review = _setup(approved_restaurant, user_client)
    _, pending = register_restaurant("p")
    reporter, _ = user_client("r")
    assert _report(reporter, "ESTABLISHMENT", pending["establishment_id"]).status_code == 404
    admin_client.post(f"{API}/admin/reviews/{review['id']}/hide", json={"category": "OTHER"})
    assert _report(reporter, "REVIEW", review["id"]).status_code == 404


def test_admins_are_notified_only_for_first_open_report(approved_restaurant, user_client, admin_client) -> None:
    _, _, _, _, review = _setup(approved_restaurant, user_client)
    for suffix in ("r", "s"):
        client, _ = user_client(suffix)
        assert _report(client, "REVIEW", review["id"]).status_code == 201
    assert notification_types(admin_client).count("ADMIN_REPORT_OPENED") == 1
    [notice] = [n for n in notifications(admin_client) if n["type"] == "ADMIN_REPORT_OPENED"]
    assert notice["link"] == "/admin/reports"


def test_daily_report_limit(approved_restaurant, user_client, monkeypatch) -> None:
    _, establishment_id, _, _, review = _setup(approved_restaurant, user_client)
    reporter, _ = user_client("r")
    monkeypatch.setattr(settings, "reports_per_day_limit", 1)
    assert _report(reporter, "REVIEW", review["id"]).status_code == 201
    assert _report(reporter, "ESTABLISHMENT", establishment_id).status_code == 429


def test_report_queue_with_preview(approved_restaurant, user_client, admin_client) -> None:
    _, establishment_id, _, author_id, review = _setup(approved_restaurant, user_client)
    for suffix in ("r", "s"):
        client, _ = user_client(suffix)
        _report(client, "REVIEW", review["id"])
    admin_client.post(f"{API}/admin/reviews/{review['id']}/block-comment", json={"category": "OFFENSIVE_LANGUAGE"})

    page = admin_client.get(f"{API}/admin/reports").json()
    assert page["total"] == 2
    item = page["items"][0]
    assert item["reports_on_target"] == 2
    assert item["reporter_email"] == "usuario-s@planati.com"
    preview = item["preview"]
    assert preview["exists"] is True and preview["owner_id"] == author_id
    assert preview["text"] == "Son unos ladrones"  # el admin ve el texto original aunque esté bloqueado
    assert preview["comment_status"] == "BLOCKED" and preview["name"] == "Parrilla A"
    assert preview["establishment_id"] == establishment_id

    reviews = admin_client.get(f"{API}/admin/reviews", params={"has_reports": True, "sort": "most_reported"}).json()
    assert reviews["items"][0]["open_reports_count"] == 2
    assert admin_client.get(f"{API}/admin/users/{author_id}").json()["open_reports_count"] == 2
    assert admin_client.get(f"{API}/admin/dashboard").json()["open_reports"] == 2
    assert admin_client.get(f"{API}/admin/reports", params={"status": "RESOLVED"}).json()["total"] == 0
    assert admin_client.get(f"{API}/admin/reports", params={"target_type": "USER"}).json()["total"] == 0


def test_resolve_block_comment_closes_all_reports_of_target(
    approved_restaurant, user_client, admin_client, db_session, make_client
) -> None:
    _, establishment_id, author, _, review = _setup(approved_restaurant, user_client)
    reporters = []
    report_ids = []
    for suffix in ("r", "s"):
        client, _ = user_client(suffix)
        reporters.append(client)
        report_ids.append(_report(client, "REVIEW", review["id"]).json()["id"])

    missing_category = admin_client.post(f"{API}/admin/reports/{report_ids[0]}/resolve", json={"action": "BLOCK_COMMENT"})
    assert missing_category.status_code == 400

    response = admin_client.post(
        f"{API}/admin/reports/{report_ids[0]}/resolve",
        json={"action": "BLOCK_COMMENT", "category": "OFFENSIVE_LANGUAGE", "note": "Insultos"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "RESOLVED" and response.json()["reports_on_target"] == 0

    assert admin_client.get(f"{API}/admin/reports").json()["total"] == 0
    resolved = admin_client.get(f"{API}/admin/reports", params={"status": "RESOLVED"}).json()["items"]
    assert {item["id"] for item in resolved} == set(report_ids)
    public = detail(make_client(), establishment_id)["recent_reviews"][0]
    assert public["comment"] is None and public["comment_blocked"] is True
    for client in reporters:
        assert notification_types(client)[0] == "REPORT_RESOLVED"
    assert "CONTENT_MODERATED" in notification_types(author)
    assert [entry.action for entry in actions(db_session)] == ["BLOCK_COMMENT", "RESOLVE_REPORT"]
    assert actions(db_session, action="RESOLVE_REPORT")[0].details["report_ids"] == report_ids

    assert admin_client.post(f"{API}/admin/reports/{report_ids[1]}/resolve", json={"action": "NONE"}).status_code == 409


def test_resolve_when_content_already_moderated(approved_restaurant, user_client, admin_client) -> None:
    _, _, _, _, review = _setup(approved_restaurant, user_client)
    reporter, _ = user_client("r")
    report_id = _report(reporter, "REVIEW", review["id"]).json()["id"]
    admin_client.post(f"{API}/admin/reviews/{review['id']}/block-comment", json={"category": "OTHER"})
    response = admin_client.post(
        f"{API}/admin/reports/{report_id}/resolve", json={"action": "BLOCK_COMMENT", "category": "OTHER"}
    )
    assert response.status_code == 200 and response.json()["status"] == "RESOLVED"


def test_resolve_suspend_owner_of_review(approved_restaurant, user_client, admin_client) -> None:
    _, _, author, author_id, review = _setup(approved_restaurant, user_client)
    reporter, _ = user_client("r")
    report_id = _report(reporter, "REVIEW", review["id"]).json()["id"]
    response = admin_client.post(
        f"{API}/admin/reports/{report_id}/resolve",
        json={"action": "SUSPEND_OWNER", "category": "OFFENSIVE_LANGUAGE", "note": "Reincidente en insultos"},
    )
    assert response.status_code == 200
    blocked = author.get(f"{API}/users/me")
    assert blocked.status_code == 403 and blocked.json()["reason"] == "Reincidente en insultos"


def test_resolve_menu_item_and_not_applicable_actions(approved_restaurant, user_client, admin_client) -> None:
    owner_client, establishment_id = approved_restaurant("a")
    product = owner_client.post(f"{API}/restaurant/products", json={"name": "Plato ofensivo", "price": "1000"}).json()
    reporter, _ = user_client("r")
    report_id = _report(reporter, "MENU_ITEM", product["id"]).json()["id"]

    not_applicable = admin_client.post(
        f"{API}/admin/reports/{report_id}/resolve", json={"action": "BLOCK_COMMENT", "category": "OTHER"}
    )
    assert not_applicable.status_code == 400
    hidden = admin_client.post(
        f"{API}/admin/reports/{report_id}/resolve", json={"action": "HIDE_CONTENT", "category": "OFFENSIVE_LANGUAGE"}
    )
    assert hidden.status_code == 200
    [item] = owner_client.get(f"{API}/restaurant/products").json()
    assert item["is_available"] is False

    establishment_report = _report(reporter, "ESTABLISHMENT", establishment_id).json()["id"]
    assert admin_client.post(
        f"{API}/admin/reports/{establishment_report}/resolve", json={"action": "DELETE_CONTENT", "category": "OTHER"}
    ).status_code == 400
    suspended = admin_client.post(
        f"{API}/admin/reports/{establishment_report}/resolve",
        json={"action": "HIDE_CONTENT", "category": "FALSE_OR_MISLEADING", "note": "Información falsa del local"},
    )
    assert suspended.status_code == 200
    assert admin_client.get(f"{API}/admin/establishments/{establishment_id}").json()["status"] == "SUSPENDED"


def test_resolve_deleted_target(approved_restaurant, user_client, admin_client) -> None:
    _, _, author, _, review = _setup(approved_restaurant, user_client)
    reporter, _ = user_client("r")
    report_id = _report(reporter, "REVIEW", review["id"]).json()["id"]
    assert author.delete(f"{API}/reviews/{review['id']}").status_code == 204

    item = admin_client.get(f"{API}/admin/reports").json()["items"][0]
    assert item["preview"]["exists"] is False
    with_action = admin_client.post(
        f"{API}/admin/reports/{report_id}/resolve", json={"action": "HIDE_CONTENT", "category": "OTHER"}
    )
    assert with_action.status_code == 404
    assert admin_client.post(f"{API}/admin/reports/{report_id}/resolve", json={"action": "NONE"}).status_code == 200


def test_dismiss_closes_all_open_reports(approved_restaurant, user_client, admin_client, db_session) -> None:
    _, _, _, _, review = _setup(approved_restaurant, user_client)
    ids = []
    for suffix in ("r", "s"):
        client, _ = user_client(suffix)
        ids.append(_report(client, "REVIEW", review["id"]).json()["id"])
    response = admin_client.post(f"{API}/admin/reports/{ids[1]}/dismiss", json={"note": "Opinión legítima"})
    assert response.status_code == 200 and response.json()["status"] == "DISMISSED"
    dismissed = admin_client.get(f"{API}/admin/reports", params={"status": "DISMISSED"}).json()
    assert dismissed["total"] == 2
    assert dismissed["items"][0]["resolution_note"] == "Opinión legítima"
    assert admin_client.post(f"{API}/admin/reports/{ids[0]}/dismiss").status_code == 409
    assert admin_client.post(f"{API}/admin/reports/9999/dismiss").status_code == 404
    assert [entry.action for entry in actions(db_session)] == ["DISMISS_REPORT"]


def test_auto_hide_after_threshold(approved_restaurant, user_client, admin_client, db_session, monkeypatch) -> None:
    _, establishment_id, author, _, review = _setup(approved_restaurant, user_client)
    monkeypatch.setattr(settings, "report_auto_hide_threshold", 2)
    first, _ = user_client("r")
    second, _ = user_client("s")
    _report(first, "REVIEW", review["id"])
    assert author.get(f"{API}/reviews/me").json()["items"][0]["status"] == "VISIBLE"
    _report(second, "REVIEW", review["id"])
    [mine] = author.get(f"{API}/reviews/me").json()["items"]
    assert mine["status"] == "HIDDEN"
    assert mine["moderation_reason"] == "Oculta automáticamente por reportes; pendiente de revisión."
    [entry] = actions(db_session, action="HIDE_REVIEW")
    assert entry.admin_id is None
    log = admin_client.get(f"{API}/admin/moderation-actions").json()["items"][0]
    assert log["admin_id"] is None and log["admin_name"] is None
