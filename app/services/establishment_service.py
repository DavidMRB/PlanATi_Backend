import math

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.establishment import Establishment, MenuItem, Schedule
from app.models.review import Review
from app.schemas.establishment import EstablishmentCreate, EstablishmentUpdate


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


async def list_establishments(
    session: AsyncSession,
    search: str | None = None,
    category: str | None = None,
) -> list[Establishment]:
    query = (
        select(Establishment)
        .options(
            selectinload(Establishment.schedules),
            selectinload(Establishment.menu_items),
            selectinload(Establishment.reviews).selectinload(Review.images),
            selectinload(Establishment.reviews).selectinload(Review.reply),
        )
        .order_by(Establishment.name)
    )
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(
            or_(Establishment.name.ilike(pattern), Establishment.category.ilike(pattern))
        )
    if category:
        query = query.where(Establishment.category.ilike(category.strip()))
    result = await session.scalars(query)
    return list(result.all())


async def get_establishment(session: AsyncSession, establishment_id: int) -> Establishment | None:
    query = (
        select(Establishment)
        .where(Establishment.id == establishment_id)
        .options(
            selectinload(Establishment.schedules),
            selectinload(Establishment.menu_items),
            selectinload(Establishment.reviews).selectinload(Review.images),
            selectinload(Establishment.reviews).selectinload(Review.reply),
        )
    )
    result = await session.scalars(query)
    return result.first()


async def list_nearby_establishments(
    session: AsyncSession,
    latitude: float,
    longitude: float,
    radius_km: float = 5.0,
    limit: int = 20,
) -> list[tuple[Establishment, float]]:
    establishments = await list_establishments(session)
    nearby: list[tuple[Establishment, float]] = []

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

    nearby.sort(key=lambda item: item[1])
    return nearby[:limit]


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


async def update_establishment(
    session: AsyncSession,
    establishment: Establishment,
    data: EstablishmentUpdate,
) -> Establishment:
    values = data.model_dump(exclude_unset=True)
    schedules = values.pop("schedules", None)
    menu_items = values.pop("menu_items", None)

    for field, value in values.items():
        setattr(establishment, field, value.strip() if isinstance(value, str) else value)
    if schedules is not None:
        establishment.schedules = [Schedule(**item.model_dump()) for item in data.schedules or []]
    if menu_items is not None:
        establishment.menu_items = [MenuItem(**item.model_dump()) for item in data.menu_items or []]

    await session.commit()
    await session.refresh(establishment)
    return establishment
