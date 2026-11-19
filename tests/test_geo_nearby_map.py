import logging
import math

import pytest

from app.core.log_filters import REDACTED_QUERY, RedactLocationQueryFilter
from app.services.establishment_service import bounding_box, haversine_km
from tests.conftest import API, CUCUTA_LAT, CUCUTA_LNG

KM_PER_DEG_LAT = 111.32
KM_PER_DEG_LNG = 111.32 * math.cos(math.radians(CUCUTA_LAT))


def offset(north_km: float = 0.0, east_km: float = 0.0) -> tuple[float, float]:
    """Punto desplazado desde el centro de Cúcuta."""
    return round(CUCUTA_LAT + north_km / KM_PER_DEG_LAT, 6), round(CUCUTA_LNG + east_km / KM_PER_DEG_LNG, 6)


def nearby(client, **params):
    query = {"latitude": CUCUTA_LAT, "longitude": CUCUTA_LNG} | params
    return client.get(f"{API}/establishments/nearby", params=query)


VIEWPORT = {"south": 7.80, "north": 7.98, "west": -72.58, "east": -72.40}


# --- bounding box ---------------------------------------------------------------------------


def test_bounding_box_contains_the_search_circle() -> None:
    south, north, west, east = bounding_box(CUCUTA_LAT, CUCUTA_LNG, 5)
    assert south < CUCUTA_LAT < north and west < CUCUTA_LNG < east
    # Cada lado está a ~5 km del centro.
    assert haversine_km(CUCUTA_LAT, CUCUTA_LNG, north, CUCUTA_LNG) == pytest.approx(5, rel=0.01)
    assert haversine_km(CUCUTA_LAT, CUCUTA_LNG, CUCUTA_LAT, east) == pytest.approx(5, rel=0.01)
    # Un punto a 4,9 km en cualquier dirección cae dentro; uno a 5,2 km al norte, fuera.
    for angle in range(0, 360, 30):
        lat, lng = offset(4.9 * math.cos(math.radians(angle)), 4.9 * math.sin(math.radians(angle)))
        assert south <= lat <= north and west <= lng <= east
    lat, _ = offset(north_km=5.2)
    assert lat > north


def test_bounding_box_never_divides_by_zero_near_the_poles() -> None:
    south, north, west, east = bounding_box(89.999, 0, 10)
    assert west < 0 < east and south < 89.999 < north


# --- /nearby --------------------------------------------------------------------------------


def test_nearby_orders_by_distance_and_excludes_outside_radius(approved_restaurant_at, make_client) -> None:
    approved_restaurant_at("centro", *offset())
    approved_restaurant_at("norte", *offset(north_km=1))
    approved_restaurant_at("este", *offset(east_km=3))
    # Dentro del cuadrado del prefiltro (4,5 km por lado) pero a ~6,4 km: lo descarta haversine.
    approved_restaurant_at("esquina", *offset(north_km=4.5, east_km=4.5))
    approved_restaurant_at("bogota", 4.711, -74.0721)

    response = nearby(make_client(), radius_km=5)
    assert response.status_code == 200
    items = response.json()
    assert [item["name"] for item in items] == ["Parrilla CENTRO", "Parrilla NORTE", "Parrilla ESTE"]
    assert [item["distance_km"] for item in items] == pytest.approx([0, 1, 3], abs=0.02)
    assert "reviews" not in items[0]
    assert {"rating_avg", "rating_count", "ranking_score", "establishment_type", "city"} <= items[0].keys()

    assert [item["name"] for item in nearby(make_client(), radius_km=5, limit=2).json()] == [
        "Parrilla CENTRO",
        "Parrilla NORTE",
    ]


def test_nearby_only_returns_approved(approved_restaurant_at, register_restaurant, make_client) -> None:
    approved_restaurant_at("aprobado", *offset(north_km=0.5))
    register_restaurant("pendiente")  # registrado en el centro, pero PENDING
    assert [item["name"] for item in nearby(make_client()).json()] == ["Parrilla APROBADO"]


def test_nearby_validates_parameters(make_client) -> None:
    client = make_client()
    assert nearby(client, radius_km=50).status_code == 200
    assert nearby(client, radius_km=50.1).status_code == 422
    assert nearby(client, radius_km=0).status_code == 422
    assert nearby(client, limit=51).status_code == 422
    assert nearby(client, sort="cercania").status_code == 422
    assert nearby(client, min_rating=0.5).status_code == 422
    assert client.get(f"{API}/establishments/nearby", params={"latitude": 91, "longitude": 0}).status_code == 422


def test_nearby_filters_and_sorts(approved_restaurant_at, add_reviews, make_client) -> None:
    _, near = approved_restaurant_at("cerca", *offset(north_km=0.5))
    _, mid = approved_restaurant_at("medio", *offset(north_km=2), establishment_type="CAFE", category="Café de especialidad")
    _, far = approved_restaurant_at("lejos", *offset(north_km=4))
    add_reviews(near, [3, 3])
    add_reviews(mid, [4, 4, 4, 4, 4, 4])
    add_reviews(far, [5, 5, 5, 5, 5, 5, 5, 5, 5, 5])
    client = make_client()

    def names(**params) -> list[str]:
        response = nearby(client, **params)
        assert response.status_code == 200, response.text
        return [item["name"].removeprefix("Parrilla ") for item in response.json()]

    assert names() == ["CERCA", "MEDIO", "LEJOS"]
    assert names(sort="rating") == ["LEJOS", "MEDIO", "CERCA"]
    # Relevancia = 0,6·(ranking − 1)/4 + 0,4·(1 − distancia/radio).
    # Radio 5 km: cerca 0,71 > medio 0,66 > lejos 0,61 (a 4 km de 5 casi no aporta cercanía).
    assert names(sort="relevance") == ["CERCA", "MEDIO", "LEJOS"]
    # Radio 10 km: las tres quedan "cerca" en proporción y gana la puntuación: lejos 0,77 > medio 0,74 > cerca 0,73.
    assert names(sort="relevance", radius_km=10) == ["LEJOS", "MEDIO", "CERCA"]
    assert names(sort="distance", radius_km=10) == ["CERCA", "MEDIO", "LEJOS"]
    assert names(establishment_type="CAFE") == ["MEDIO"]
    assert names(category="café de especialidad") == ["MEDIO"]
    assert names(min_rating=4) == ["MEDIO", "LEJOS"]


def test_relevance_prefers_closer_place_when_rating_is_equal(approved_restaurant_at, add_reviews, make_client) -> None:
    _, near = approved_restaurant_at("cerca", *offset(north_km=4))
    _, far = approved_restaurant_at("lejos", *offset(north_km=1))
    add_reviews(near, [4, 4])
    add_reviews(far, [4, 4])
    names = [item["name"] for item in nearby(make_client(), sort="relevance").json()]
    assert names == ["Parrilla LEJOS", "Parrilla CERCA"]  # "lejos" está más cerca del usuario


# --- /map -----------------------------------------------------------------------------------


def test_map_returns_markers_in_viewport(approved_restaurant_at, register_restaurant, make_client) -> None:
    _, inside = approved_restaurant_at("dentro", *offset(north_km=1))
    approved_restaurant_at("fuera", 4.711, -74.0721)
    register_restaurant("pendiente")  # en el centro pero PENDING

    response = make_client().get(f"{API}/establishments/map", params=VIEWPORT)
    assert response.status_code == 200
    body = response.json()
    assert body["truncated"] is False
    (marker,) = body["items"]
    assert marker["id"] == inside
    assert set(marker) == {
        "id", "name", "category", "establishment_type", "latitude", "longitude",
        "rating_avg", "rating_count", "price_range", "profile_image_url",
    }
    assert float(marker["latitude"]) == pytest.approx(offset(north_km=1)[0])


def test_map_truncates_keeping_best_ranked(approved_restaurant_at, add_reviews, make_client) -> None:
    _, low = approved_restaurant_at("baja", *offset(north_km=1))
    _, high = approved_restaurant_at("alta", *offset(north_km=2))
    _, unrated = approved_restaurant_at("nueva", *offset(north_km=3))
    add_reviews(low, [2, 2, 2])
    add_reviews(high, [5, 5, 5])

    client = make_client()
    full = client.get(f"{API}/establishments/map", params=VIEWPORT).json()
    assert [item["id"] for item in full["items"]] == [high, unrated, low]
    assert full["truncated"] is False

    truncated = client.get(f"{API}/establishments/map", params=VIEWPORT | {"limit": 2}).json()
    assert [item["id"] for item in truncated["items"]] == [high, unrated]
    assert truncated["truncated"] is True

    exact = client.get(f"{API}/establishments/map", params=VIEWPORT | {"limit": 3}).json()
    assert exact["truncated"] is False

    rated = client.get(f"{API}/establishments/map", params=VIEWPORT | {"min_rating": 3}).json()
    assert [item["id"] for item in rated["items"]] == [high]


def test_map_rejects_invalid_viewport(make_client) -> None:
    client = make_client()
    inverted_lat = VIEWPORT | {"south": 7.98, "north": 7.80}
    inverted_lng = VIEWPORT | {"west": -72.40, "east": -72.58}
    assert client.get(f"{API}/establishments/map", params=inverted_lat).status_code == 400
    assert client.get(f"{API}/establishments/map", params=inverted_lng).status_code == 400
    assert client.get(f"{API}/establishments/map", params=VIEWPORT | {"limit": 501}).status_code == 422
    assert client.get(f"{API}/establishments/map", params={"south": 7.8, "north": 7.9}).status_code == 422


# --- Directorio -----------------------------------------------------------------------------


def test_directory_has_no_reviews_and_supports_sort_filters_and_paging(
    approved_restaurant_at, register_restaurant, add_reviews, make_client
) -> None:
    _, a = approved_restaurant_at("a", *offset(), establishment_name="Zeta Grill")
    _, b = approved_restaurant_at("b", *offset(north_km=1), establishment_name="Alfa Café", establishment_type="CAFE")
    _, c = approved_restaurant_at("c", *offset(north_km=2), establishment_name="Media Luna")
    register_restaurant("d")  # PENDING: nunca aparece
    add_reviews(a, [5])  # 1 reseña de 5★ → ranking 3,75
    add_reviews(b, [5, 4, 5, 5, 4, 5, 5, 4, 5, 5])  # 10 reseñas, 4,7 → ranking ≈ 4,3
    client = make_client()

    def ids(**params) -> list[int]:
        response = client.get(f"{API}/establishments", params=params)
        assert response.status_code == 200, response.text
        return [item["id"] for item in response.json()]

    listing = client.get(f"{API}/establishments").json()
    assert "reviews" not in listing[0]
    assert listing[0]["rating_count"] == 10 and listing[0]["rating_avg"] == 4.7

    assert ids() == [b, a, c]  # ranking: más reseñas buenas > una sola de 5★ > sin reseñas
    assert ids(sort="rating") == [a, b, c]  # promedio puro, sin reseñas al final
    assert ids(sort="reviews") == [b, a, c]
    assert ids(sort="name") == [b, c, a]
    assert ids(sort="recent") == [c, b, a]
    assert ids(establishment_type="CAFE") == [b]
    assert ids(min_rating=4.8) == [a]
    assert ids(search="luna") == [c]
    assert ids(skip=1, limit=1) == [a]
    assert client.get(f"{API}/establishments", params={"limit": 51}).status_code == 422
    assert client.get(f"{API}/establishments", params={"sort": "precio"}).status_code == 422
    assert client.get(f"{API}/establishments", params={"establishment_type": "AVION"}).status_code == 422


# --- Logs -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/api/v1/establishments/nearby?latitude=7.88&longitude=-72.49", f"/api/v1/establishments/nearby?{REDACTED_QUERY}"),
        ("/api/v1/establishments/map?north=8&south=7&east=-72&west=-73", f"/api/v1/establishments/map?{REDACTED_QUERY}"),
        ("/api/v1/establishments?search=pizza", "/api/v1/establishments?search=pizza"),
        ("/api/v1/establishments/nearby", "/api/v1/establishments/nearby"),
    ],
)
def test_access_log_hides_user_location(path: str, expected: str) -> None:
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d', ("127.0.0.1:5000", "GET", path, "1.1", 200), None
    )
    assert RedactLocationQueryFilter().filter(record) is True
    assert record.args[2] == expected
    assert "7.88" not in record.getMessage() or path == expected
