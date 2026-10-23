import asyncio

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models.user import User
from app.services.auth_service import authenticate_google_user

GOOGLE_IDENTITY = {
    "google_sub": "sub-123",
    "email": "persona@gmail.com",
    "email_verified": True,
    "name": "Nombre de Google",
    "picture": "https://lh3.googleusercontent.com/google-photo",
}


def test_google_login_does_not_overwrite_profile_edits() -> None:
    asyncio.run(_run())


async def _run() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        # Primer ingreso: se toma la foto y el nombre de Google.
        user, _ = await authenticate_google_user(session, GOOGLE_IDENTITY)
        assert user.picture == GOOGLE_IDENTITY["picture"]
        assert user.full_name == "Nombre de Google"

        # El usuario edita su perfil.
        user.picture = "https://pub.r2.dev/avatars/mia.png"
        user.full_name = "Nombre Editado"
        await session.commit()

        # Un nuevo ingreso con Google no debe revertir esos cambios.
        user, _ = await authenticate_google_user(session, GOOGLE_IDENTITY)
        assert user.picture == "https://pub.r2.dev/avatars/mia.png"
        assert user.full_name == "Nombre Editado"

        # Si no tiene foto, Google la vuelve a completar.
        user.picture = None
        await session.commit()
        user, _ = await authenticate_google_user(session, GOOGLE_IDENTITY)
        assert user.picture == GOOGLE_IDENTITY["picture"]

        # Cuenta existente por correo que se vincula a Google por primera vez: conserva su foto propia.
        other = User(
            full_name="Otra Persona",
            email="otra@gmail.com",
            password_hash="x",
            picture="https://pub.r2.dev/avatars/otra.png",
        )
        session.add(other)
        await session.commit()
        linked, _ = await authenticate_google_user(
            session, {**GOOGLE_IDENTITY, "google_sub": "sub-456", "email": "otra@gmail.com"}
        )
        assert linked.picture == "https://pub.r2.dev/avatars/otra.png"
