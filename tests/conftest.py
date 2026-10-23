from collections.abc import AsyncGenerator, Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

import app.models  # noqa: F401  (registra todos los modelos en Base.metadata)
from app.api.dependencies import get_db
from app.core.security import hash_password
from app.db.base import Base
from app.main import app
from app.models.user import User

API = "/api/v1"
DEFAULT_PASSWORD = "Password123!"


@pytest.fixture
def database_path(tmp_path) -> Iterator[str]:
    # Archivo temporal (no :memory:) para compartir datos entre conexiones y bucles de eventos.
    path = tmp_path / "test.db"
    sync_engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    yield str(path)


@pytest.fixture
def app_with_db(database_path: str) -> Iterator[None]:
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}", poolclass=NullPool)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def make_client(app_with_db: None) -> Iterator[Callable[[], TestClient]]:
    """Cada cliente tiene su propio cookie jar, es decir, su propia sesión."""
    clients: list[TestClient] = []

    def factory() -> TestClient:
        client = TestClient(app)
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.close()


@pytest.fixture
def create_user(database_path: str) -> Callable[..., None]:
    def factory(email: str, role: str = "user", password: str = DEFAULT_PASSWORD) -> None:
        engine = create_engine(f"sqlite:///{database_path}")
        with Session(engine) as session:
            session.add(
                User(
                    full_name=f"Test {role}",
                    email=email,
                    password_hash=hash_password(password),
                    role=role,
                    phone_verified=True,
                    status="ACTIVE",
                )
            )
            session.commit()
        engine.dispose()

    return factory


@pytest.fixture
def admin_client(make_client, create_user) -> TestClient:
    create_user("admin@planati.com", role="admin")
    client = make_client()
    response = client.post(f"{API}/auth/login", json={"email": "admin@planati.com", "password": DEFAULT_PASSWORD})
    assert response.status_code == 200, response.text
    return client


def restaurant_payload(suffix: str = "a", **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "account_email": f"gerencia-{suffix}@restaurante.com",
        "password": DEFAULT_PASSWORD,
        "manager_name": "Carlos Gómez",
        "establishment_name": f"Parrilla {suffix.upper()}",
        "category": "Parrilla y Asados",
        "address": "Calle 100 # 15-20, Bogotá",
        "establishment_phone": "+573001234567",
        "contact_email": f"contacto-{suffix}@restaurante.com",
        "description": "Carnes a la parrilla y platos típicos",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def register_restaurant(make_client) -> Callable[..., tuple[TestClient, dict[str, object]]]:
    def factory(suffix: str = "a", **overrides: object) -> tuple[TestClient, dict[str, object]]:
        client = make_client()
        response = client.post(f"{API}/auth/restaurant/register", json=restaurant_payload(suffix, **overrides))
        assert response.status_code == 201, response.text
        return client, response.json()

    return factory


@pytest.fixture
def approved_restaurant(register_restaurant, admin_client) -> Callable[[str], tuple[TestClient, int]]:
    def factory(suffix: str = "a") -> tuple[TestClient, int]:
        client, data = register_restaurant(suffix)
        establishment_id = data["establishment_id"]
        response = admin_client.post(f"{API}/admin/establishments/{establishment_id}/approve")
        assert response.status_code == 200, response.text
        return client, establishment_id

    return factory
