"""Comprueba los fixtures compartidos que usan las fases siguientes."""

import asyncio
from decimal import Decimal

from sqlalchemy import func, select

from app.models.establishment import Establishment
from app.models.user import User
from tests.conftest import API


def test_user_client_is_active_verified_user(user_client) -> None:
    client, user_id = user_client("a")
    other, other_id = user_client("b")
    me = client.get(f"{API}/users/me").json()
    assert me["id"] == user_id != other_id
    assert (me["role"], me["status"], me["phone_verified"]) == ("user", "ACTIVE", True)
    assert other.get(f"{API}/users/me").json()["phone_number"] != me["phone_number"]


def test_approved_restaurant_at_and_db_session(approved_restaurant_at, db_session) -> None:
    _, establishment_id = approved_restaurant_at("a", 7.8891, -72.4967)

    async def scenario() -> Establishment | None:
        async with db_session() as session:
            return await session.get(Establishment, establishment_id)

    establishment = asyncio.run(scenario())
    assert establishment is not None
    assert establishment.status == "APPROVED"
    assert (establishment.latitude, establishment.longitude) == (Decimal("7.889100"), Decimal("-72.496700"))

    async def count_users() -> int:
        async with db_session() as session:
            return await session.scalar(select(func.count(User.id)))

    # Segunda llamada con otro bucle de eventos: la fábrica de sesiones sigue sirviendo.
    assert asyncio.run(count_users()) == 2  # admin + cuenta del restaurante
