import os

# Antes de importar la app: el ciclo de recordatorios no debe arrancar en las pruebas.
os.environ.setdefault("REMINDERS_ENABLED", "false")

import asyncio  # noqa: E402
from collections.abc import AsyncGenerator, Callable, Iterator  # noqa: E402
from decimal import Decimal  # noqa: E402

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

import app.models  # noqa: E402,F401  (registra todos los modelos en Base.metadata)
from app.api.dependencies import get_db  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.core.csrf import CSRF_HEADER_NAME  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.main import app  # noqa: E402
from app.models.user import User  # noqa: E402

API = "/api/v1"
DEFAULT_PASSWORD = "Password123!"
# Origen de confianza por defecto (FRONTEND_URL / CORS_ORIGINS de desarrollo).
TRUSTED_ORIGIN = "http://localhost:3000"
# Centro de Cúcuta: ubicación por defecto de los restaurantes de prueba.
CUCUTA_LAT, CUCUTA_LNG = 7.8891, -72.4967


@pytest.fixture
def database_path(tmp_path) -> Iterator[str]:
    # Archivo temporal (no :memory:) para compartir datos entre conexiones y bucles de eventos.
    path = tmp_path / "test.db"
    sync_engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    yield str(path)


@pytest.fixture
def session_factory(database_path: str) -> async_sessionmaker[AsyncSession]:
    # NullPool: cada asyncio.run() abre y cierra sus propias conexiones en su propio bucle de eventos.
    engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}", poolclass=NullPool)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def db_session(session_factory: async_sessionmaker[AsyncSession]) -> async_sessionmaker[AsyncSession]:
    """Sesiones asíncronas sobre la base temporal de la prueba, para llamar servicios directamente.

    Uso (no hay pytest-asyncio):

        async def scenario():
            async with db_session() as session:
                ...
        asyncio.run(scenario())
    """
    return session_factory


@pytest.fixture
def app_with_db(session_factory: async_sessionmaker[AsyncSession]) -> Iterator[None]:
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)


def _remember_csrf_token(client: TestClient) -> Callable[[httpx.Response], None]:
    """Copia `csrf_token` de las respuestas de autenticación a la cabecera X-CSRF-Token del cliente,
    como hace el frontend. Así las pruebas existentes no tienen que manejar el token una por una."""

    def hook(response: httpx.Response) -> None:
        if not response.request.url.path.startswith(f"{API}/auth/"):
            return
        if "application/json" not in response.headers.get("content-type", ""):
            return
        response.read()
        try:
            body = response.json()
        except ValueError:
            return
        if isinstance(body, dict) and isinstance(body.get("csrf_token"), str):
            client.headers[CSRF_HEADER_NAME] = body["csrf_token"]

    return hook


@pytest.fixture
def make_client(app_with_db: None) -> Iterator[Callable[[], TestClient]]:
    """Cada cliente tiene su propio cookie jar, es decir, su propia sesión.

    Envía `Origin` de confianza y el token CSRF de su sesión, como el navegador con el frontend.
    """
    clients: list[TestClient] = []

    def factory() -> TestClient:
        client = TestClient(app, headers={"Origin": TRUSTED_ORIGIN})
        client.event_hooks = {"request": [], "response": [_remember_csrf_token(client)]}
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.close()


@pytest.fixture
def create_user(database_path: str) -> Callable[..., int]:
    def factory(email: str, role: str = "user", password: str = DEFAULT_PASSWORD, **fields: object) -> int:
        values: dict[str, object] = {
            "full_name": f"Test {role}",
            "email": email,
            "password_hash": hash_password(password),
            "role": role,
            "phone_verified": True,
            "status": "ACTIVE",
            # Nacen con las versiones legales vigentes aceptadas (B8); pasar None para probar CONSENT_REQUIRED.
            "privacy_policy_version": settings.privacy_policy_version,
            "terms_version": settings.terms_version,
        }
        values.update(fields)
        engine = create_engine(f"sqlite:///{database_path}")
        with Session(engine) as session:
            user = User(**values)
            session.add(user)
            session.commit()
            user_id = user.id
        engine.dispose()
        return user_id

    return factory


def login(client: TestClient, email: str, password: str = DEFAULT_PASSWORD) -> None:
    response = client.post(f"{API}/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


@pytest.fixture
def admin_client(make_client, create_user) -> TestClient:
    create_user("admin@planati.com", role="admin")
    client = make_client()
    login(client, "admin@planati.com")
    return client


@pytest.fixture
def user_client(make_client, create_user) -> Callable[[str], tuple[TestClient, int]]:
    """Usuario `user` activo con teléfono verificado y sesión iniciada: `client, user_id = user_client("a")`."""
    counter = iter(range(1, 10_000))

    def factory(suffix: str = "a") -> tuple[TestClient, int]:
        email = f"usuario-{suffix}@planati.com"
        user_id = create_user(
            email,
            full_name=f"Usuario {suffix.upper()}",
            nickname=f"usuario{suffix}",
            phone_number=f"+57300{next(counter):07d}",
        )
        client = make_client()
        login(client, email)
        return client, user_id

    return factory


def _coordinate(value: float) -> str:
    return str(Decimal(str(value)).quantize(Decimal("0.000001")))


def consent_fields() -> dict[str, object]:
    """Casillas de aceptación que exigen los registros, con las versiones vigentes (B8)."""
    return {
        "accept_privacy_policy": True,
        "accept_terms": True,
        "privacy_policy_version": settings.privacy_policy_version,
        "terms_version": settings.terms_version,
    }


def restaurant_payload(suffix: str = "a", **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        **consent_fields(),
        "account_email": f"gerencia-{suffix}@restaurante.com",
        "password": DEFAULT_PASSWORD,
        "manager_name": "Carlos Gómez",
        "establishment_name": f"Parrilla {suffix.upper()}",
        "category": "Parrilla y Asados",
        "address": "Av. 0 # 11-50, Caobos, Cúcuta",
        "establishment_phone": "+573001234567",
        "contact_email": f"contacto-{suffix}@restaurante.com",
        "description": "Carnes a la parrilla y platos típicos",
        "latitude": _coordinate(CUCUTA_LAT),
        "longitude": _coordinate(CUCUTA_LNG),
        "location_source": "MAP_PIN",
        "city": "Cúcuta",
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
def approved_restaurant(register_restaurant, admin_client) -> Callable[..., tuple[TestClient, int]]:
    def factory(suffix: str = "a", **overrides: object) -> tuple[TestClient, int]:
        client, data = register_restaurant(suffix, **overrides)
        establishment_id = data["establishment_id"]
        response = admin_client.post(f"{API}/admin/establishments/{establishment_id}/approve")
        assert response.status_code == 200, response.text
        return client, establishment_id

    return factory


@pytest.fixture
def add_reviews(db_session) -> Callable[[int, list[int]], None]:
    """Crea reseñas con esas estrellas (cada una de un autor distinto) y recalcula los agregados."""
    counter = iter(range(1, 100_000))

    def factory(establishment_id: int, ratings: list[int]) -> None:
        from app.models.review import Review
        from app.services.rating_service import recalculate_establishment_rating

        async def scenario() -> None:
            async with db_session() as session:
                for rating in ratings:
                    author = User(
                        full_name="Autor de reseña",
                        email=f"autor-{next(counter)}@planati.com",
                        password_hash="no-se-usa",
                        role="user",
                        phone_verified=True,
                        status="ACTIVE",
                    )
                    session.add(author)
                    await session.flush()
                    session.add(Review(user_id=author.id, establishment_id=establishment_id, rating=rating, comment="Reseña"))
                await session.flush()
                await recalculate_establishment_rating(session, establishment_id)
                await session.commit()

        asyncio.run(scenario())

    return factory


@pytest.fixture
def approved_restaurant_at(approved_restaurant) -> Callable[..., tuple[TestClient, int]]:
    """Como `approved_restaurant`, pero registrado en coordenadas concretas (y con otros campos opcionales)."""

    def factory(suffix: str, latitude: float, longitude: float, **overrides: object) -> tuple[TestClient, int]:
        return approved_restaurant(
            suffix, latitude=_coordinate(latitude), longitude=_coordinate(longitude), **overrides
        )

    return factory
