"""Datos dummy para pruebas: crea y elimina restaurantes, menú, usuarios y reseñas.

Uso (desde la carpeta Backend, con la base de datos levantada y migrada):

    python -m scripts.seed_demo up [--restaurants 8] [--users 15]
    python -m scripts.seed_demo status
    python -m scripts.seed_demo down

Todos los datos demo cuelgan de usuarios con email @demo.planati.test. `down`
borra esos usuarios y, por cascada, todo lo asociado (establecimientos, horarios,
menú, combos, imágenes, reseñas y respuestas). No toca datos reales.

Contraseña de todas las cuentas demo: Demo12345!
"""

import argparse
import asyncio
import random
from datetime import time
from decimal import Decimal

from sqlalchemy import delete, func, select

from app.core.security import hash_password
from app.db.session import engine, session_factory
from app.models import *  # noqa: F401,F403  (registra todos los modelos)
from app.models.establishment import ComboItem, Establishment, EstablishmentImage, MenuItem, Schedule
from app.models.review import Review, ReviewImage, ReviewReply
from app.models.user import User

DEMO_DOMAIN = "demo.planati.test"
DEMO_PASSWORD = "Demo12345!"

CATEGORIES = ["Colombiana", "Italiana", "Mexicana", "Asiática", "Parrilla", "Cafetería", "Comida rápida", "Vegetariana"]
PRICE_RANGES = ["$", "$$", "$$$"]
PRODUCTS = [
    ("Bandeja paisa", 28000), ("Ajiaco", 24000), ("Hamburguesa clásica", 21000), ("Pizza margarita", 26000),
    ("Tacos al pastor", 19000), ("Sushi roll", 32000), ("Churrasco", 38000), ("Ensalada de la casa", 15000),
    ("Limonada de coco", 9000), ("Café americano", 5000), ("Brownie", 8000), ("Jugo natural", 7000),
]
COMMENTS = [
    "Excelente atención y la comida llegó rápido.", "Muy buen sabor, volvería sin dudarlo.",
    "El lugar es agradable pero la espera fue larga.", "Porciones generosas y buen precio.",
    "No me convenció, esperaba más por lo que cobran.", "Lo mejor de la zona, totalmente recomendado.",
    "Buen ambiente para ir en grupo.", "Servicio regular, la comida estaba bien.",
]
REPLIES = ["¡Gracias por tu visita!", "Lamentamos la espera, vamos a mejorar.", "Te esperamos pronto."]
# Centro aproximado de Bogotá; cada restaurante se desplaza un poco.
BASE_LAT, BASE_LON = Decimal("4.711000"), Decimal("-74.072100")


def _email(kind: str, n: int) -> str:
    return f"{kind}{n}@{DEMO_DOMAIN}"


async def seed(n_restaurants: int, n_users: int) -> None:
    rng = random.Random(42)
    async with session_factory() as session:
        if await session.scalar(select(func.count()).select_from(User).where(User.email.like(f"%@{DEMO_DOMAIN}"))):
            print("Ya existen datos demo. Ejecuta `down` primero.")
            return

        pwd = hash_password(DEMO_PASSWORD)
        users = [
            User(
                full_name=f"Usuario Demo {i}", nickname=f"demo{i}", email=_email("user", i),
                phone_number=f"+5730000{i:05d}", phone_verified=True, status="ACTIVE",
                password_hash=pwd, role="user",
            )
            for i in range(1, n_users + 1)
        ]
        session.add_all(users)

        establishments: list[Establishment] = []
        for i in range(1, n_restaurants + 1):
            owner = User(
                full_name=f"Dueño Demo {i}", email=_email("owner", i), phone_verified=False,
                status="ACTIVE", password_hash=pwd, role="restaurant",
            )
            est = Establishment(
                owner=owner, name=f"Restaurante Demo {i}", category=CATEGORIES[(i - 1) % len(CATEGORIES)],
                description=f"Restaurante de prueba número {i}.", address=f"Calle {10 + i} # {i}-{20 + i}, Bogotá",
                latitude=BASE_LAT + Decimal(rng.uniform(-0.04, 0.04)).quantize(Decimal("0.000001")),
                longitude=BASE_LON + Decimal(rng.uniform(-0.04, 0.04)).quantize(Decimal("0.000001")),
                price_range=rng.choice(PRICE_RANGES),
                # El último queda PENDING para probar el flujo de aprobación del admin.
                status="PENDING" if i == n_restaurants and n_restaurants > 1 else "APPROVED",
                phone=f"+5731000{i:05d}", contact_email=_email("contacto", i), manager_name=f"Gerente {i}",
                profile_image_url=f"https://picsum.photos/seed/demo{i}-profile/400/400",
                banner_image_url=f"https://picsum.photos/seed/demo{i}-banner/1600/500",
            )
            est.schedules = [Schedule(day_of_week=d, opening_time=time(11, 0), closing_time=time(22, 0)) for d in range(7)]
            products = [
                MenuItem(
                    name=name, description=f"{name} de la casa.", price=Decimal(price), is_combo=False,
                    image_url=f"https://picsum.photos/seed/demo{i}-{name.replace(' ', '')}/600/400",
                )
                for name, price in rng.sample(PRODUCTS, 6)
            ]
            est.menu_items = products
            est.images = [
                EstablishmentImage(image_url=f"https://picsum.photos/seed/demo{i}-{k}/800/600", image_type="GALLERY", display_order=k)
                for k in range(3)
            ]
            session.add(est)
            establishments.append(est)

        await session.flush()  # asigna ids

        for est in establishments:
            products = [m for m in est.menu_items if not m.is_combo]
            combo = MenuItem(
                establishment_id=est.id, name="Combo Demo", description="Combo de prueba.",
                price=sum((p.price for p in products[:2]), Decimal(0)) * Decimal("0.9"), is_combo=True,
                image_url=f"https://picsum.photos/seed/demo{est.id}-combo/600/400",
            )
            session.add(combo)
            await session.flush()
            session.add_all(ComboItem(combo_id=combo.id, product_id=p.id, quantity=1) for p in products[:2])

            if est.status != "APPROVED":
                continue
            for reviewer in rng.sample(users, min(len(users), rng.randint(2, 6))):
                review = Review(
                    user_id=reviewer.id, establishment_id=est.id,
                    rating=rng.randint(1, 5), comment=rng.choice(COMMENTS),
                )
                session.add(review)
                await session.flush()
                if rng.random() < 0.3:
                    session.add(ReviewImage(review_id=review.id, image_url=f"https://picsum.photos/seed/r{review.id}/600/400"))
                if rng.random() < 0.4:
                    session.add(ReviewReply(review_id=review.id, establishment_id=est.id, comment=rng.choice(REPLIES)))

        await session.commit()
    print(f"Creados {n_restaurants} restaurantes y {n_users} usuarios demo (con menú, combos y reseñas).")
    print(f"Emails: owner1..owner{n_restaurants}@{DEMO_DOMAIN}, user1..user{n_users}@{DEMO_DOMAIN}")
    print(f"Contraseña: {DEMO_PASSWORD}")


async def status() -> None:
    async with session_factory() as session:
        demo_ids = select(User.id).where(User.email.like(f"%@{DEMO_DOMAIN}"))
        n_users = await session.scalar(select(func.count()).select_from(User).where(User.id.in_(demo_ids)))
        n_est = await session.scalar(select(func.count()).select_from(Establishment).where(Establishment.owner_id.in_(demo_ids)))
        n_rev = await session.scalar(select(func.count()).select_from(Review).where(Review.user_id.in_(demo_ids)))
    print(f"Datos demo: {n_users} usuarios, {n_est} establecimientos, {n_rev} reseñas.")


async def teardown() -> None:
    async with session_factory() as session:
        # combo_items.product_id es ON DELETE RESTRICT: si la cascada borra un producto antes que
        # su combo, Postgres falla. Por eso se eliminan primero las composiciones de combos demo.
        demo_est_ids = (
            select(Establishment.id).join(User, Establishment.owner_id == User.id).where(User.email.like(f"%@{DEMO_DOMAIN}"))
        )
        demo_menu_ids = select(MenuItem.id).where(MenuItem.establishment_id.in_(demo_est_ids))
        await session.execute(delete(ComboItem).where(ComboItem.combo_id.in_(demo_menu_ids)))
        # El resto sí cae por ON DELETE CASCADE.
        result = await session.execute(delete(User).where(User.email.like(f"%@{DEMO_DOMAIN}")))
        await session.commit()
    print(f"Eliminados {result.rowcount} usuarios demo y todo lo asociado.")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("up", help="Crea los datos demo")
    up.add_argument("--restaurants", type=int, default=8)
    up.add_argument("--users", type=int, default=15)
    sub.add_parser("status", help="Cuenta los datos demo existentes")
    sub.add_parser("down", help="Elimina todos los datos demo")
    args = parser.parse_args()
    try:
        if args.cmd == "up":
            await seed(args.restaurants, args.users)
        elif args.cmd == "status":
            await status()
        else:
            await teardown()
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
