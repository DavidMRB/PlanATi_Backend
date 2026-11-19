# Servicio de establecimientos: directorio público, detalle, búsqueda de cercanos, mapa, registro y edición.
# GUIA #10 TEMA: Subalgoritmos (funciones, procedimientos y modularización) -> modularización: cada operación del negocio es una función de este módulo;
# las rutas (app/api/routes/establishments.py) solo reciben la petición y llaman a estas funciones.
import math
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Any, Literal

from sqlalchemy import Select, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload, selectinload

from app.core.config import settings
from app.models.establishment import ComboItem, Establishment, MenuItem, Schedule
from app.schemas.establishment import EstablishmentCreate, EstablishmentUpdate
from app.services.rating_service import relevance_score


# GUIA #10 TEMA: Subalgoritmos (funciones, procedimientos y modularización) -> función con parámetros y `return`: distancia en km entre dos coordenadas
# (fórmula de haversine). `radius_km`, `a` y `c` son variables locales: solo existen dentro de la función.
def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_km = 6371.0
    lat1_rad = math.radians(lat1)
    lon1_rad = math.radians(lon1)
    lat2_rad = math.radians(lat2)
    lon2_rad = math.radians(lon2)

    delta_lat = lat2_rad - lat1_rad
    delta_lon = lon2_rad - lon1_rad

    a = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_km * c


# Detalle: horarios, menú con la composición de cada combo e imágenes, en consultas por nivel.
_DETAIL_LOAD_OPTIONS = (
    selectinload(Establishment.schedules),
    selectinload(Establishment.menu_items).selectinload(MenuItem.combo_items).joinedload(ComboItem.product),
    selectinload(Establishment.images),
    # Las reseñas no se cargan: el detalle trae solo las recientes (review_service.recent_reviews).
    raiseload(Establishment.reviews),
)


# Directorio público: filtra por estado, texto, categoría, tipo y puntuación; ordena y pagina en la base de datos.
async def list_establishments(
    session: AsyncSession,
    search: str | None = None,
    category: str | None = None,
    approved_only: bool = True,
    *,
    establishment_type: str | None = None,
    min_rating: float | None = None,
    sort: "DirectorySort" = "ranking",
    skip: int = 0,
    limit: int | None = None,
) -> list[Establishment]:
    query = (
        select(Establishment)
        .options(*_LIST_LOAD_OPTIONS)
        .order_by(*DIRECTORY_ORDER[sort])
    )
    if approved_only:
        query = query.where(Establishment.status == "APPROVED")
    # GUIA #8 TEMA: Vectores (ordenamiento y búsqueda) -> búsqueda por atributo (nombre o categoría) sin importar mayúsculas: `strip()` + `ilike`.
    # GUIA #7 TEMA: Cadenas, listas, tuplas y diccionarios -> la f-string arma el patrón '%texto%'.
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(
            or_(Establishment.name.ilike(pattern), Establishment.category.ilike(pattern))
        )
    if category:
        query = query.where(Establishment.category.ilike(category.strip()))
    query = _apply_filters(query, establishment_type=establishment_type, min_rating=min_rating)
    query = query.offset(skip).limit(limit)
    result = await session.scalars(query)
    return list(result.all())


# Detalle de un establecimiento por id (None si no existe; la ruta responde 404).
# GUIA #8 TEMA: Vectores (ordenamiento y búsqueda) -> búsqueda por llave primaria indexada en la base de datos, sin recorrer la lista con un `for`.
async def get_establishment(session: AsyncSession, establishment_id: int) -> Establishment | None:
    query = (
        select(Establishment)
        .where(Establishment.id == establishment_id)
        .options(*_DETAIL_LOAD_OPTIONS)
    )
    result = await session.scalars(query)
    return result.first()


# Lugares cercanos al usuario dentro de `radius_km`, ordenados según `sort` (distancia, calificación o relevancia).
async def list_nearby_establishments(
    session: AsyncSession,
    latitude: float,
    longitude: float,
    radius_km: float = 5.0,
    limit: int = 20,
    *,
    category: str | None = None,
    establishment_type: str | None = None,
    min_rating: float | None = None,
    sort: "NearbySort" = "distance",
) -> list[tuple[Establishment, float]]:
    # 1. Prefiltro en SQL: solo los aprobados dentro del cuadrado que contiene el círculo de búsqueda.
    establishments = await _approved_in_bounds(
        session, *bounding_box(latitude, longitude, radius_km),
        category=category, establishment_type=establishment_type, min_rating=min_rating,
    )
    # GUIA #7 TEMA: Cadenas, listas, tuplas y diccionarios -> lista local de tuplas inmutables (establecimiento, distancia).
    nearby: list[tuple[Establishment, float]] = []

    # 2. Distancia exacta con haversine solo sobre ese subconjunto.
    # GUIA #6 TEMA: Ciclos -> `for` recorre los establecimientos; `continue` salta los que no tienen coordenadas
    # y el `if` dentro del ciclo conserva solo los que están dentro del radio.
    for establishment in establishments:
        if establishment.latitude is None or establishment.longitude is None:
            continue

        distance = haversine_km(
            latitude,
            longitude,
            float(establishment.latitude),
            float(establishment.longitude),
        )
        if distance <= radius_km:
            nearby.append((establishment, distance))

    # GUIA #8 TEMA: Vectores (ordenamiento y búsqueda) -> ordenamiento con `sort()` + `key=lambda` (ascendente por distancia, posición 1 de la tupla);
    # rating y relevance ordenan de mayor a menor con el signo menos. `nearby[:limit]` toma los primeros N.
    # GUIA #10 TEMA: Subalgoritmos (funciones, procedimientos y modularización) -> la `lambda` es el criterio de orden y llama a la función `relevance_score`.
    # 3. Orden según `sort` (sort() es estable: a igual criterio, queda el más cercano primero).
    nearby.sort(key=lambda item: item[1])
    if sort == "rating":
        nearby.sort(key=lambda item: (-(item[0].rating_avg or 0), -item[0].rating_count))
    elif sort == "relevance":
        nearby.sort(key=lambda item: -relevance_score(item[0].ranking_score, item[1], radius_km))
    return nearby[:limit]


# Registro de un establecimiento nuevo con sus horarios y su menú.
# GUIA #7 TEMA: Cadenas, listas, tuplas y diccionarios -> `strip()` limpia las cadenas y las comprensiones de lista crean horarios y menú;
# `session.add()` cumple el papel de `append()`, pero sobre la tabla de PostgreSQL.
async def create_establishment(
    session: AsyncSession,
    owner_id: int,
    data: EstablishmentCreate,
) -> Establishment:
    establishment = Establishment(
        owner_id=owner_id,
        name=data.name.strip(),
        category=data.category.strip(),
        description=data.description.strip(),
        address=data.address.strip(),
        latitude=data.latitude,
        longitude=data.longitude,
        price_range=data.price_range,
        schedules=[Schedule(**schedule.model_dump()) for schedule in data.schedules],
        menu_items=[MenuItem(**item.model_dump()) for item in data.menu_items],
    )
    session.add(establishment)
    await session.commit()
    await session.refresh(establishment)
    return establishment


# Actualización parcial: solo cambia los campos que llegaron en la petición.
async def update_establishment(
    session: AsyncSession,
    establishment: Establishment,
    data: EstablishmentUpdate,
) -> Establishment:
    values = data.model_dump(exclude_unset=True)
    schedules = values.pop("schedules", None)
    menu_items = values.pop("menu_items", None)

    # GUIA #7 TEMA: Cadenas, listas, tuplas y diccionarios -> `model_dump(exclude_unset=True)` devuelve un diccionario {campo: valor} con lo enviado.
    # GUIA #6 TEMA: Ciclos -> `for` sobre `.items()` aplica cada campo editado.
    for field, value in values.items():
        setattr(establishment, field, value.strip() if isinstance(value, str) else value)
    if schedules is not None:
        establishment.schedules = [Schedule(**item.model_dump()) for item in data.schedules or []]
    if menu_items is not None:
        establishment.menu_items = [MenuItem(**item.model_dump()) for item in data.menu_items or []]

    await session.commit()
    await session.refresh(establishment)
    return establishment


# --- Listado, cercanos y mapa (fase 2, B2) ----------------------------------------------------

# Listado y cercanos no cargan reseñas: el JSON ya no crece con el volumen de opiniones.
# raiseload hace que un acceso accidental a `establishment.reviews` falle en vez de consultar.
_LIST_LOAD_OPTIONS = (
    selectinload(Establishment.schedules),
    selectinload(Establishment.menu_items).selectinload(MenuItem.combo_items).joinedload(ComboItem.product),
    selectinload(Establishment.images),
    raiseload(Establishment.reviews),
)

DirectorySort = Literal["ranking", "rating", "reviews", "recent", "name"]
NearbySort = Literal["distance", "rating", "relevance"]

_RANKING_DESC = Establishment.ranking_score.desc().nulls_last()
# GUIA #8 TEMA: Vectores (ordenamiento y búsqueda) -> criterios de orden del directorio en la base de datos: ascendente (`name`, alfabético)
# o descendente con `.desc()` (ranking, rating, reviews, recent).
# GUIA #7 TEMA: Cadenas, listas, tuplas y diccionarios -> diccionario: clave = criterio, valor = tupla de columnas.
DIRECTORY_ORDER: dict[str, tuple[Any, ...]] = {
    "ranking": (_RANKING_DESC, Establishment.rating_count.desc(), Establishment.name, Establishment.id),
    "rating": (
        Establishment.rating_avg.desc().nulls_last(),
        Establishment.rating_count.desc(),
        Establishment.name,
        Establishment.id,
    ),
    "reviews": (Establishment.rating_count.desc(), _RANKING_DESC, Establishment.name, Establishment.id),
    "recent": (Establishment.created_at.desc(), Establishment.id.desc()),
    "name": (Establishment.name, Establishment.id),
}

OUT_OF_SERVICE_AREA_MESSAGE = "La ubicación está fuera del área de servicio de PlanATi."
_COORDINATE_STEP = Decimal("0.000001")


class OutOfServiceAreaError(Exception):
    """El punto cae fuera de SERVICE_AREA_BOUNDS (400)."""


# GUIA #10 TEMA: Subalgoritmos (funciones, procedimientos y modularización) -> procedimiento (`-> None`): no devuelve un valor; lanza una excepción si el punto
# queda fuera de la zona de servicio.
def ensure_in_service_area(latitude: Decimal | float | None, longitude: Decimal | float | None) -> None:
    if latitude is None or longitude is None or settings.service_area is None:
        return
    south, west, north, east = settings.service_area
    if not (south <= float(latitude) <= north and west <= float(longitude) <= east):
        raise OutOfServiceAreaError(OUT_OF_SERVICE_AREA_MESSAGE)


# GUIA #10 TEMA: Subalgoritmos (funciones, procedimientos y modularización) -> función que devuelve una tupla: el cuadrado de búsqueda que se usa como prefiltro en SQL.
def bounding_box(lat: float, lng: float, radius_km: float) -> tuple[float, float, float, float]:
    """(sur, norte, oeste, este) del cuadrado que contiene el círculo de `radius_km` alrededor del punto.

    No se trata el cruce del antimeridiano (±180°): el servicio opera en Colombia.
    """
    delta_lat = radius_km / 111.32
    delta_lng = radius_km / (111.32 * max(math.cos(math.radians(lat)), 0.01))
    return lat - delta_lat, lat + delta_lat, lng - delta_lng, lng + delta_lng


def _bound(value: float, rounding: str) -> Decimal:
    # Mismo tipo que la columna Numeric(9, 6), para que PostgreSQL use el índice (latitude, longitude).
    return Decimal(str(value)).quantize(_COORDINATE_STEP, rounding=rounding)


def _within(query: Select, south: float, north: float, west: float, east: float) -> Select:
    return query.where(
        Establishment.status == "APPROVED",
        Establishment.latitude.is_not(None),
        Establishment.longitude.is_not(None),
        Establishment.latitude.between(_bound(south, ROUND_FLOOR), _bound(north, ROUND_CEILING)),
        Establishment.longitude.between(_bound(west, ROUND_FLOOR), _bound(east, ROUND_CEILING)),
    )


# Filtros comunes del directorio, los cercanos y el mapa.
# GUIA #10 TEMA: Subalgoritmos (funciones, procedimientos y modularización) -> paso de argumentos: se reasigna el parámetro `query` en cada filtro y se devuelve;
# la consulta original del llamador no cambia.
def _apply_filters(
    query: Select,
    *,
    category: str | None = None,
    establishment_type: str | None = None,
    min_rating: float | None = None,
) -> Select:
    if category:
        query = query.where(Establishment.category.ilike(category.strip()))
    if establishment_type:
        query = query.where(Establishment.establishment_type == establishment_type)
    if min_rating is not None:
        query = query.where(Establishment.rating_avg >= min_rating)
    return query


async def _approved_in_bounds(
    session: AsyncSession,
    south: float,
    north: float,
    west: float,
    east: float,
    **filters: Any,
) -> list[Establishment]:
    query = _within(select(Establishment).options(*_LIST_LOAD_OPTIONS), south, north, west, east)
    result = await session.scalars(_apply_filters(query, **filters))
    return list(result.all())


MAP_MARKER_COLUMNS = (
    Establishment.id,
    Establishment.name,
    Establishment.category,
    Establishment.establishment_type,
    Establishment.latitude,
    Establishment.longitude,
    Establishment.rating_avg,
    Establishment.rating_count,
    Establishment.price_range,
    Establishment.profile_image_url,
)


# Marcadores del mapa para el área visible: lista de diccionarios y un indicador de truncado.
async def list_map_markers(
    session: AsyncSession,
    *,
    south: float,
    west: float,
    north: float,
    east: float,
    limit: int,
    category: str | None = None,
    establishment_type: str | None = None,
    min_rating: float | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Marcadores del área visible, mejor posicionados primero. Devuelve (marcadores, truncado)."""
    query = _within(select(*MAP_MARKER_COLUMNS), south, north, west, east)
    query = _apply_filters(query, category=category, establishment_type=establishment_type, min_rating=min_rating)
    # Se ordena antes de cortar (si hay más de `limit`, quedan los mejores) y se pide uno de más
    # para saber si la respuesta quedó truncada.
    query = query.order_by(*DIRECTORY_ORDER["ranking"]).limit(limit + 1)
    # GUIA #7 TEMA: Cadenas, listas, tuplas y diccionarios -> cada fila se convierte en un diccionario {columna: valor}.
    rows = [dict(row._mapping) for row in (await session.execute(query)).all()]
    return rows[:limit], len(rows) > limit
