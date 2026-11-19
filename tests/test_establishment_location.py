import asyncio
from decimal import Decimal

from app.models.establishment import Establishment
from tests.conftest import API, restaurant_payload

MADRID = {"latitude": "40.416800", "longitude": "-3.703800"}


def _profile(client) -> dict:
    return client.get(f"{API}/restaurant/profile").json()


def test_register_requires_coordinates(make_client) -> None:
    client = make_client()
    for missing in ("latitude", "longitude"):
        payload = restaurant_payload("a")
        del payload[missing]
        assert client.post(f"{API}/auth/restaurant/register", json=payload).status_code == 422
    payload = restaurant_payload("a", latitude=None, longitude=None)
    assert client.post(f"{API}/auth/restaurant/register", json=payload).status_code == 422


def test_register_validates_location_fields(make_client) -> None:
    client = make_client()
    out_of_area = client.post(f"{API}/auth/restaurant/register", json=restaurant_payload("a", **MADRID))
    assert out_of_area.status_code == 400
    assert out_of_area.json()["detail"] == "La ubicación está fuera del área de servicio de PlanATi."

    bad_source = restaurant_payload("b", location_source="SATELITE")
    assert client.post(f"{API}/auth/restaurant/register", json=bad_source).status_code == 422
    bad_type = restaurant_payload("c", establishment_type="AVION")
    assert client.post(f"{API}/auth/restaurant/register", json=bad_type).status_code == 422
    bad_latitude = restaurant_payload("d", latitude="95")
    assert client.post(f"{API}/auth/restaurant/register", json=bad_latitude).status_code == 422


def test_register_stores_location_and_rounds_gps_precision(register_restaurant) -> None:
    client, _ = register_restaurant(
        "a",
        latitude=7.88912345678,
        longitude=-72.49671234,
        location_source="ADDRESS",
        google_place_id="  ChIJ-lugar-de-prueba  ",
        city=" Cúcuta ",
        establishment_type="BAR",
    )
    profile = _profile(client)
    assert (Decimal(profile["latitude"]), Decimal(profile["longitude"])) == (Decimal("7.889123"), Decimal("-72.496712"))
    assert profile["location_source"] == "ADDRESS"
    assert profile["google_place_id"] == "ChIJ-lugar-de-prueba"
    assert profile["city"] == "Cúcuta"
    assert profile["establishment_type"] == "BAR"
    assert profile["rating_count"] == 0 and profile["rating_avg"] is None
    assert profile["ranking_score"] == 3.5  # valor previo del ranking bayesiano


def test_type_defaults_to_restaurant(register_restaurant) -> None:
    client, _ = register_restaurant("a")
    assert _profile(client)["establishment_type"] == "RESTAURANT"


def test_profile_update_validates_location(approved_restaurant) -> None:
    client, _ = approved_restaurant("a")

    only_latitude = client.patch(f"{API}/restaurant/profile", json={"latitude": "7.9"})
    assert only_latitude.status_code == 422
    cleared = client.patch(f"{API}/restaurant/profile", json={"latitude": None, "longitude": None})
    assert cleared.status_code == 422
    out_of_area = client.patch(f"{API}/restaurant/profile", json=MADRID)
    assert out_of_area.status_code == 400
    null_type = client.patch(f"{API}/restaurant/profile", json={"establishment_type": None})
    assert null_type.status_code == 422

    moved = client.patch(
        f"{API}/restaurant/profile",
        json={"latitude": "7.900000", "longitude": "-72.500000", "location_source": "GPS", "establishment_type": "CAFE"},
    )
    assert moved.status_code == 200, moved.text
    body = moved.json()
    assert (body["latitude"], body["longitude"], body["location_source"]) == ("7.900000", "-72.500000", "GPS")
    assert body["establishment_type"] == "CAFE"

    # Otros campos se editan sin reenviar la ubicación.
    assert client.patch(f"{API}/restaurant/profile", json={"name": "Nuevo nombre"}).status_code == 200
    assert _profile(client)["latitude"] == "7.900000"


def test_pending_restaurant_cannot_change_location(register_restaurant) -> None:
    client, _ = register_restaurant("a")
    response = client.patch(f"{API}/restaurant/profile", json={"latitude": "7.9", "longitude": "-72.5"})
    assert response.status_code == 403


def test_reapply_accepts_and_validates_location(register_restaurant, admin_client) -> None:
    client, data = register_restaurant("a")
    rejected = admin_client.post(
        f"{API}/admin/establishments/{data['establishment_id']}/reject", json={"reason": "Ubicación incorrecta"}
    )
    assert rejected.status_code == 200

    assert client.patch(f"{API}/restaurant/reapply", json=MADRID).status_code == 400
    assert client.patch(f"{API}/restaurant/reapply", json={"longitude": "-72.5"}).status_code == 422
    reapplied = client.patch(
        f"{API}/restaurant/reapply", json={"latitude": "7.91", "longitude": "-72.51", "location_source": "MAP_PIN"}
    )
    assert reapplied.status_code == 200, reapplied.text
    profile = _profile(client)
    assert (profile["latitude"], profile["status"]) == ("7.910000", "PENDING")


def test_approve_warns_when_establishment_has_no_location(admin_client, create_user, db_session) -> None:
    owner_id = create_user("legado@restaurante.com", role="restaurant")

    async def create_legacy() -> int:
        async with db_session() as session:
            establishment = Establishment(
                owner_id=owner_id, name="Local legado", category="Comida", description="Sin ubicación",
                address="Centro", status="PENDING",
            )
            session.add(establishment)
            await session.commit()
            return establishment.id

    establishment_id = asyncio.run(create_legacy())
    response = admin_client.post(f"{API}/admin/establishments/{establishment_id}/approve")
    assert response.status_code == 200
    assert response.json()["warnings"] == ["El establecimiento no tiene ubicación y no aparecerá en el mapa."]


def test_approve_with_location_has_no_warnings(register_restaurant, admin_client) -> None:
    _, data = register_restaurant("a")
    response = admin_client.post(f"{API}/admin/establishments/{data['establishment_id']}/approve")
    assert response.json()["warnings"] == []


def test_registered_restaurant_appears_on_map_once_approved(register_restaurant, admin_client, make_client) -> None:
    _, data = register_restaurant("a")
    viewport = {"south": 7.8, "north": 7.98, "west": -72.58, "east": -72.4}
    visitor = make_client()
    assert visitor.get(f"{API}/establishments/map", params=viewport).json()["items"] == []
    nearby_params = {"latitude": 7.8891, "longitude": -72.4967}
    assert visitor.get(f"{API}/establishments/nearby", params=nearby_params).json() == []

    admin_client.post(f"{API}/admin/establishments/{data['establishment_id']}/approve")
    assert [m["id"] for m in visitor.get(f"{API}/establishments/map", params=viewport).json()["items"]] == [
        data["establishment_id"]
    ]
    assert [e["id"] for e in visitor.get(f"{API}/establishments/nearby", params=nearby_params).json()] == [
        data["establishment_id"]
    ]
