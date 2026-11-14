"""Utilidades compartidas por las pruebas de administración y moderación (B5)."""

import asyncio

from sqlalchemy import select

from app.core.config import settings
from app.models.moderation import ModerationAction
from tests.conftest import API

REASON = "Incumple las normas de la comunidad."


def image(name: str) -> str:
    return f"{settings.r2_public_base_url.rstrip('/')}/reviews/{name}.jpg"


def post_review(client, establishment_id: int, **body) -> dict:
    body.setdefault("rating", 4)
    response = client.post(f"{API}/reviews/establishments/{establishment_id}", json=body)
    assert response.status_code == 201, response.text
    return response.json()


def detail(client, establishment_id: int) -> dict:
    response = client.get(f"{API}/establishments/{establishment_id}")
    assert response.status_code == 200, response.text
    return response.json()


def notifications(client) -> list[dict]:
    response = client.get(f"{API}/notifications", params={"limit": 50})
    assert response.status_code == 200, response.text
    return response.json()["items"]


def notification_types(client) -> list[str]:
    return [item["type"] for item in notifications(client)]


def actions(db_session, **filters) -> list[ModerationAction]:
    async def scenario() -> list[ModerationAction]:
        async with db_session() as session:
            query = select(ModerationAction).order_by(ModerationAction.id)
            for name, value in filters.items():
                query = query.where(getattr(ModerationAction, name) == value)
            return list((await session.scalars(query)).all())

    return asyncio.run(scenario())
