"""Datos dummy para pruebas en Cúcuta: crea y elimina establecimientos, menú, usuarios y reseñas.

Uso (desde la carpeta PlanATi_Backend, con la base de datos levantada y migrada):

    python -m scripts.seed_demo up [--restaurants 12] [--users 15]
    python -m scripts.seed_demo status
    python -m scripts.seed_demo down

Todos los datos demo cuelgan de usuarios con email @demo.planati.test. `down`
borra esos usuarios y, por cascada, todo lo asociado (establecimientos, horarios,
menú, combos, imágenes, reseñas, respuestas y notificaciones). No toca datos reales.
Antes de `down`, haz una copia: `python -m scripts.backup_db create --tag pre-pruebas`.

Los locales se reparten al azar en un radio de ~4 km alrededor del centro de Cúcuta
(7.889100, -72.496700). Las coordenadas son aproximadas y no tienen por qué coincidir
con la dirección escrita, que usa barrios reales de la ciudad. Hay restaurantes, cafés,
un bar con horario que cruza la medianoche, un hotel, una tienda y una experiencia sin
horarios (para probar ese caso). El último local queda PENDING para probar la aprobación.

Moderación (B5): una cuenta admin demo (admin1@…), un comentario bloqueado, otro bloqueado y
reescrito por su autor (pendiente de revisión), una reseña oculta por spam, una respuesta bloqueada,
reportes abiertos sobre una reseña, el último usuario suspendido y un local suspendido.

Planes (B6): user1 tiene un plan próximo con platos y recordatorio y uno ya completado; user2, uno
para mañana y otro cancelado. Las horas caen dentro de los horarios del local.

Favoritos (B7): user1 tiene tres favoritos (uno es el local suspendido, que no se lista) y user2, uno.

Contraseña de todas las cuentas demo: Demo12345!
"""

import argparse
import asyncio
import math
import random
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import delete, func, select

from app.core.security import hash_password
from app.db.session import engine, session_factory
from app.models import *  # noqa: F401,F403  (registra todos los modelos)
from app.models.establishment import ComboItem, Establishment, EstablishmentImage, MenuItem, Schedule
from app.models.favorite import Favorite
from app.models.notification import NotificationType
from app.models.moderation import ModerationAction
from app.models.plan import Plan, PlanItem
from app.models.privacy import Consent
from app.models.report import Report
from app.models.review import Review, ReviewImage, ReviewReply
from app.models.user import User
from app.core.time import LOCAL_TZ, UTC, utcnow
from app.services import admin_service, moderation_service
from app.services.schedule_service import is_open_at
from app.services.notification_service import notify, notify_admins
from app.services.rating_service import recompute_all_ratings
from app.services.privacy_service import record_consents

DEMO_DOMAIN = "demo.planati.test"
DEMO_PASSWORD = "Demo12345!"
CITY = "Cúcuta"
# Centro de Cúcuta; cada local se desplaza al azar dentro de SPREAD_KM (casco urbano).
BASE_LAT, BASE_LNG = 7.889100, -72.496700
SPREAD_KM = 4.0
COORD_STEP = Decimal("0.000001")
# Cómo se habría ubicado cada local en el registro (el frontend lo informa en location_source).
LOCATION_SOURCES = ["GPS", "ADDRESS", "MAP_PIN", "MANUAL"]


@dataclass(frozen=True)
class DemoPlace:
    name: str
    kind: str  # establishment_type: RESTAURANT, CAFE, BAR, HOTEL, EXPERIENCE, STORE
    category: str
    neighborhood: str
    street: str
    price_range: str
    menu: str  # clave de PRODUCTS
    schedule: str | None  # clave de SCHEDULES; None = sin horarios publicados


PLACES = [
    DemoPlace("Fogón Cucuteño", "RESTAURANT", "Comida típica nortesantandereana", "Centro", "Calle 10 # 4-35", "$", "tipica", "lunch"),
    DemoPlace("La Brasa de Caobos", "RESTAURANT", "Parrilla y asados", "Caobos", "Av. 0 # 11-50", "$$$", "parrilla", "lunch_dinner"),
    DemoPlace("Rápido y Sabroso", "RESTAURANT", "Comida rápida", "Quinta Oriental", "Calle 15 # 1E-20", "$", "rapida", "all_day"),
    DemoPlace("Café La Riviera", "CAFE", "Café de especialidad", "La Riviera", "Av. 1E # 16-40", "$$", "cafe", "cafe"),
    DemoPlace("Bar El Malecón", "BAR", "Bar y coctelería", "Prados del Este", "Av. Libertadores # 10-80", "$$", "bar", "night"),
    DemoPlace("Hotel Puerta de la Frontera", "HOTEL", "Hotel con restaurante", "Los Acacios", "Av. 4 # 8-120", "$$$", "hotel", "hotel"),
    DemoPlace("Ruta del Sabor Cucuteño", "EXPERIENCE", "Recorrido gastronómico", "La Ceiba", "Calle 20 # 7-15", "$$", "experiencia", None),
    DemoPlace("Arepas de Atalaya", "RESTAURANT", "Comida típica nortesantandereana", "Atalaya", "Av. 7 # 1-90", "$", "tipica", "breakfast_lunch"),
    DemoPlace("Pastelería Barrio Blanco", "CAFE", "Panadería y repostería", "Barrio Blanco", "Calle 13 # 0-62", "$", "panaderia", "cafe"),
    DemoPlace("Mercadito de San Luis", "STORE", "Productos regionales", "San Luis", "Av. 6 # 22-14", "$", "tienda", "store"),
    DemoPlace("Guaimaral Grill", "RESTAURANT", "Parrilla y asados", "Guaimaral", "Calle 5N # 3-40", "$$", "parrilla", "lunch_dinner"),
    DemoPlace("Sazón de la Abuela", "RESTAURANT", "Comida casera", "Centro", "Av. 5 # 9-71", "$$", "casera", "lunch"),
]

ALL_DAYS = range(7)  # 0 = lunes … 6 = domingo
# (días, apertura, cierre). Si el cierre es menor que la apertura, el tramo cruza la medianoche.
SCHEDULES: dict[str, list[tuple[range | tuple[int, ...], time, time]]] = {
    "lunch": [(ALL_DAYS, time(11, 0), time(16, 0))],
    "lunch_dinner": [(ALL_DAYS, time(11, 30), time(15, 0)), ((1, 2, 3, 4, 5, 6), time(18, 0), time(22, 30))],
    "all_day": [(ALL_DAYS, time(10, 0), time(23, 0))],
    "breakfast_lunch": [(range(6), time(6, 30), time(15, 0)), ((6,), time(7, 0), time(13, 0))],
    "cafe": [(range(6), time(7, 0), time(19, 0)), ((6,), time(8, 0), time(14, 0))],
    "night": [((2, 3, 4, 5), time(18, 0), time(2, 0))],
    "hotel": [(ALL_DAYS, time(6, 0), time(23, 0))],
    "store": [(range(6), time(8, 0), time(18, 0))],
}

PRODUCTS: dict[str, list[tuple[str, int]]] = {
    "tipica": [
        ("Pastel de garbanzo", 4500), ("Mute santandereano", 18000), ("Hayaca cucuteña", 12000),
        ("Carne oreada con yuca", 26000), ("Arepa de maíz pelao", 6000), ("Cebada cucuteña", 5000),
        ("Chicha de arroz", 5000),
    ],
    "parrilla": [
        ("Churrasco", 39000), ("Punta de anca", 42000), ("Costillas BBQ", 36000), ("Chorizo con arepa", 9000),
        ("Picada mixta", 48000), ("Limonada de coco", 9000),
    ],
    "rapida": [
        ("Hamburguesa clásica", 21000), ("Perro caliente", 12000), ("Salchipapa", 14000),
        ("Papas a la francesa", 8000), ("Sándwich de pollo", 16000), ("Jugo natural", 6000),
    ],
    "casera": [
        ("Almuerzo del día", 16000), ("Sancocho de gallina", 22000), ("Sobrebarriga en salsa", 27000),
        ("Cabrito con pepitoria", 38000), ("Arroz con leche", 6000), ("Jugo natural", 6000),
    ],
    "cafe": [
        ("Tinto campesino", 2500), ("Café americano", 5000), ("Capuchino", 7500), ("Pandebono", 3000),
        ("Torta de zanahoria", 8000), ("Cheesecake de maracuyá", 11000), ("Granizado de café", 9500),
    ],
    "panaderia": [
        ("Pandebono", 3000), ("Almojábana", 3000), ("Croissant de queso", 5500), ("Milhoja", 7000),
        ("Torta de zanahoria", 8000), ("Tinto campesino", 2500),
    ],
    "bar": [
        ("Cóctel de maracuyá", 22000), ("Mojito", 24000), ("Michelada", 14000), ("Cerveza artesanal", 12000),
        ("Picada para compartir", 45000), ("Alitas BBQ", 28000),
    ],
    "hotel": [
        ("Desayuno buffet", 35000), ("Almuerzo ejecutivo", 25000), ("Cena a la carta", 60000),
        ("Pasadía con piscina", 80000), ("Noche en habitación doble", 280000),
    ],
    "experiencia": [
        ("Recorrido gastronómico por el centro", 70000), ("Taller de arepas", 55000),
        ("Cata de café de Norte de Santander", 45000), ("Recorrido histórico y almuerzo típico", 90000),
    ],
    "tienda": [
        ("Café molido 500 g", 22000), ("Bocadillo veleño", 8000), ("Dulce de leche cortada", 12000),
        ("Mermelada de mora", 14000), ("Pasteles de garbanzo para llevar (6)", 24000),
    ],
}

COMMENTS = [
    "Excelente atención y la comida llegó rápido.", "El pastel de garbanzo estaba buenísimo, volvería sin dudarlo.",
    "El lugar es agradable pero la espera fue larga.", "Porciones generosas y buen precio.",
    "No me convenció, esperaba más por lo que cobran.", "Lo mejor de la zona, totalmente recomendado.",
    "Buen ambiente para ir en grupo, con aire acondicionado, que se agradece con este calor.",
    "Servicio regular, la comida estaba bien.", "Ideal para llevar a quien visita Cúcuta por primera vez.",
]
REPLIES = ["¡Gracias por tu visita!", "Lamentamos la espera, vamos a mejorar.", "Te esperamos pronto."]
# Textos de ejemplo para la moderación demo (se conservan en la base de datos; en público se ve el aviso).
BLOCKED_TEXTS = [
    "El mesero es un inútil, no vuelvo a este antro.",
    "Pregunten por Carlos, su número es 3001234567, siempre atiende mal.",
]
REWRITTEN_TEXT = "Me atendieron mal, aunque la comida estaba bien."
SPAM_TEXT = "Visita mi página y gana dinero desde casa: www.ganafacil.example"
BLOCKED_REPLY_TEXT = "Si no le gustó no vuelva, aquí no necesitamos clientes como usted."


def _email(kind: str, n: int) -> str:
    return f"{kind}{n}@{DEMO_DOMAIN}"


def _random_point(rng: random.Random) -> tuple[Decimal, Decimal]:
    """Punto uniforme dentro de un círculo de SPREAD_KM alrededor del centro."""
    distance = SPREAD_KM * math.sqrt(rng.random())
    bearing = rng.uniform(0, 2 * math.pi)
    lat = BASE_LAT + (distance * math.cos(bearing)) / 111.32
    lng = BASE_LNG + (distance * math.sin(bearing)) / (111.32 * math.cos(math.radians(BASE_LAT)))
    return Decimal(str(lat)).quantize(COORD_STEP), Decimal(str(lng)).quantize(COORD_STEP)


def _schedules(key: str | None) -> list[Schedule]:
    if key is None:
        return []
    return [
        Schedule(day_of_week=day, opening_time=opening, closing_time=closing)
        for days, opening, closing in SCHEDULES[key]
        for day in days
    ]


def _place(i: int) -> DemoPlace:
    place = PLACES[(i - 1) % len(PLACES)]
    rounds = (i - 1) // len(PLACES)
    return place if rounds == 0 else replace(place, name=f"{place.name} {rounds + 1}")


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
        admin = User(
            full_name="Admin Demo", nickname="admin_demo", email=_email("admin", 1),
            phone_number="+573009999999", phone_verified=True, status="ACTIVE", password_hash=pwd, role="admin",
        )
        session.add(admin)

        establishments: list[Establishment] = []
        for i in range(1, n_restaurants + 1):
            place = _place(i)
            # Igual que POST /auth/restaurant/register: sin OTP; el acceso depende de la aprobación.
            owner = User(
                full_name=f"Dueño Demo {i}", email=_email("owner", i), phone_verified=True,
                status="ACTIVE", password_hash=pwd, role="restaurant",
            )
            latitude, longitude = _random_point(rng)
            est = Establishment(
                owner=owner, name=place.name, category=place.category,
                description=f"{place.category} en el barrio {place.neighborhood} de {CITY}.",
                address=f"{place.street}, {place.neighborhood}, {CITY}",
                latitude=latitude, longitude=longitude, price_range=place.price_range,
                city=CITY, establishment_type=place.kind, location_source=LOCATION_SOURCES[(i - 1) % len(LOCATION_SOURCES)],
                # El último queda PENDING para probar el flujo de aprobación del admin.
                status="PENDING" if i == n_restaurants and n_restaurants > 1 else "APPROVED",
                phone=f"+5731000{i:05d}", contact_email=_email("contacto", i), manager_name=f"Gerente {i}",
                profile_image_url=f"https://picsum.photos/seed/cucuta{i}-profile/400/400",
                banner_image_url=f"https://picsum.photos/seed/cucuta{i}-banner/1600/500",
            )
            est.schedules = _schedules(place.schedule)
            catalog = PRODUCTS[place.menu]
            est.menu_items = [
                MenuItem(
                    name=name, description=f"{name} de la casa.", price=Decimal(price), is_combo=False,
                    image_url=f"https://picsum.photos/seed/cucuta{i}-p{k}/600/400",
                )
                for k, (name, price) in enumerate(rng.sample(catalog, min(len(catalog), 6)))
            ]
            est.images = [
                EstablishmentImage(image_url=f"https://picsum.photos/seed/cucuta{i}-{k}/800/600", image_type="GALLERY", display_order=k)
                for k in range(3)
            ]
            session.add(est)
            establishments.append(est)

        await session.flush()  # asigna ids
        # Consentimientos (B8): todas las cuentas demo aceptaron las versiones vigentes al registrarse.
        for account in [*users, admin]:
            record_consents(session, account, "WEB_REGISTER", ip_address=None, user_agent="seed_demo")
        for est in establishments:
            record_consents(session, est.owner, "RESTAURANT_REGISTER", ip_address=None, user_agent="seed_demo")

        review_ids: list[tuple[int, bool]] = []  # (id, tiene comentario)
        reply_ids: list[int] = []
        for est in establishments:
            products = [m for m in est.menu_items if not m.is_combo]
            combo = MenuItem(
                establishment_id=est.id, name="Combo de la casa", description=f"{products[0].name} + {products[1].name}.",
                price=(sum((p.price for p in products[:2]), Decimal(0)) * Decimal("0.9")).quantize(Decimal("1")),
                is_combo=True, image_url=f"https://picsum.photos/seed/cucuta{est.id}-combo/600/400",
            )
            session.add(combo)
            await session.flush()
            session.add_all(ComboItem(combo_id=combo.id, product_id=p.id, quantity=1) for p in products[:2])

            if est.status != "APPROVED":
                continue
            # Notificación de aprobación, como la que crea POST /admin/establishments/{id}/approve.
            approved = await notify(
                session, est.owner_id, NotificationType.ESTABLISHMENT_APPROVED, "¡Tu establecimiento fue aprobado!",
                f"{est.name} ya es visible en PlanATi. Completa tu perfil, tu menú y tus fotos para atraer más visitas.",
                link="/restaurant/dashboard", data={"establishment_id": est.id},
            )
            if rng.random() < 0.5 and approved is not None:
                approved.read_at = func.now()
            for reviewer in rng.sample(users, min(len(users), rng.randint(2, 6))):
                review = Review(
                    user_id=reviewer.id, establishment_id=est.id,
                    # Una de cada cinco reseñas es solo de estrellas (el comentario es opcional).
                    rating=rng.randint(1, 5), comment=None if rng.random() < 0.2 else rng.choice(COMMENTS),
                )
                session.add(review)
                await session.flush()
                review_ids.append((review.id, review.comment is not None))
                if rng.random() < 0.3:
                    session.add(ReviewImage(review_id=review.id, image_url=f"https://picsum.photos/seed/r{review.id}/600/400"))
                if rng.random() < 0.4:
                    reply = ReviewReply(review_id=review.id, establishment_id=est.id, comment=rng.choice(REPLIES))
                    session.add(reply)
                    await session.flush()
                    reply_ids.append(reply.id)

        await session.flush()
        await _seed_plans(session, users, establishments)
        _seed_favorites(session, users, establishments)
        await _seed_moderation(session, rng, admin, users, establishments, review_ids, reply_ids)

        # Promedio, conteo y ranking bayesiano de cada local (los usa el directorio y el mapa).
        await session.flush()
        await recompute_all_ratings(session)
        await session.commit()
    print(f"Creados {n_restaurants} establecimientos en {CITY} y {n_users} usuarios demo (con menú, combos, reseñas y notificaciones).")
    print(f"Emails: owner1..owner{n_restaurants}@{DEMO_DOMAIN}, user1..user{n_users}@{DEMO_DOMAIN}, admin1@{DEMO_DOMAIN}")
    print(f"Contraseña: {DEMO_PASSWORD}")


def _open_slot(est: Establishment, days_ahead: int) -> datetime:
    """Primera hora en punto (12:00–21:00, hora de Colombia) en que el local abre, desde `days_ahead` días."""
    base = utcnow().astimezone(LOCAL_TZ).date() + timedelta(days=days_ahead)
    for offset in range(7):
        for hour in (19, 13, 12, 20, 18, 21, 14, 15, 16, 17):
            candidate = datetime.combine(base + timedelta(days=offset), time(hour, 0), tzinfo=LOCAL_TZ)
            if not est.schedules or is_open_at(est.schedules, candidate):
                return candidate
    return datetime.combine(base, time(12, 0), tzinfo=LOCAL_TZ)


def _demo_plan(user: User, est: Establishment, when: datetime, *, status: str = "SCHEDULED",
               reminder: int | None = None, party_size: int = 2, quantities: tuple[int, ...] = ()) -> Plan:
    products = [m for m in est.menu_items if not m.is_combo and m.is_available]
    items = [
        PlanItem(menu_item_id=p.id, name_snapshot=p.name, unit_price_snapshot=p.price, quantity=q)
        for p, q in zip(products, quantities)
    ]
    scheduled_at = when.astimezone(UTC).replace(second=0, microsecond=0)  # siempre en UTC
    return Plan(
        user_id=user.id, establishment_id=est.id, title=f"Plan en {est.name}", scheduled_at=scheduled_at,
        party_size=party_size, status=status, reminder_minutes_before=reminder,
        reminder_at=scheduled_at - timedelta(minutes=reminder) if reminder else None,
        total_amount=sum((i.unit_price_snapshot * i.quantity for i in items), Decimal(0)), items=items,
    )


async def _seed_plans(session, users: list[User], establishments: list[Establishment]) -> None:
    """Planes demo creados directamente (como los dejaría POST /plans), con el total del catálogo."""
    approved = [est for est in establishments if est.status == "APPROVED"]
    if len(approved) < 3 or len(users) < 2:
        return
    session.add_all([
        _demo_plan(users[0], approved[0], _open_slot(approved[0], 3), reminder=120, party_size=4, quantities=(2, 1)),
        _demo_plan(users[0], approved[1], _open_slot(approved[1], -3), status="COMPLETED", quantities=(1,)),
        _demo_plan(users[1], approved[2], _open_slot(approved[2], 1), reminder=60, quantities=(1, 1, 1)),
        _demo_plan(users[1], approved[0], _open_slot(approved[0], 5), status="CANCELLED"),
    ])
    await session.flush()


def _seed_favorites(session, users: list[User], establishments: list[Establishment]) -> None:
    approved = [est for est in establishments if est.status == "APPROVED"]
    if len(approved) < 3 or len(users) < 2:
        return
    # approved[-1] es el que _seed_moderation suspende: sigue guardado pero no se lista.
    for user, places in ((users[0], (approved[0], approved[2], approved[-1])), (users[1], (approved[1],))):
        session.add_all([Favorite(user_id=user.id, establishment_id=est.id) for est in places])


async def _seed_moderation(
    session,
    rng: random.Random,
    admin: User,
    users: list[User],
    establishments: list[Establishment],
    review_ids: list[tuple[int, bool]],
    reply_ids: list[int],
) -> None:
    """Casos de moderación con los mismos servicios que la consola admin (bitácora y notificaciones)."""
    with_comment = [review_id for review_id, has_comment in review_ids if has_comment]
    picks = rng.sample(with_comment, min(4, len(with_comment)))
    if len(picks) > 0:
        review = await moderation_service.get_review(session, picks[0])
        review.comment = BLOCKED_TEXTS[0]
        await moderation_service.block_review_comment(
            session, admin, review, category="OFFENSIVE_LANGUAGE", note="Contiene insultos al personal."
        )
    if len(picks) > 1:
        review = await moderation_service.get_review(session, picks[1])
        review.comment = BLOCKED_TEXTS[1]
        await moderation_service.block_review_comment(session, admin, review, category="PERSONAL_DATA")
        # El autor reescribió el comentario: sigue bloqueado y queda pendiente de revisión.
        review.comment = REWRITTEN_TEXT
        review.flagged_for_review = True
        review.edited_at = func.now()
    if len(picks) > 2:
        review = await moderation_service.get_review(session, picks[2])
        review.comment = SPAM_TEXT
        await moderation_service.hide_review(
            session, admin, review, category="SPAM_OR_ADVERTISING", reason="Publicidad de otro negocio."
        )
    if len(picks) > 3:
        review = await moderation_service.get_review(session, picks[3])
        reporters = [user for user in users if user.id != review.user_id][:2]
        for reporter, reason in zip(reporters, ["OFFENSIVE", "FALSE_INFO"]):
            session.add(
                Report(
                    reporter_id=reporter.id, target_type="REVIEW", target_id=review.id, reason=reason,
                    details="Reporte de prueba (seed demo).",
                )
            )
        await notify_admins(
            session, NotificationType.ADMIN_REPORT_OPENED, "Nuevo reporte de contenido",
            "Se reportó una reseña por: Contenido ofensivo.", link="/admin/reports",
            data={"target_type": "REVIEW", "target_id": review.id},
        )
    if reply_ids:
        reply = await moderation_service.get_reply(session, reply_ids[0])
        reply.comment = BLOCKED_REPLY_TEXT
        await moderation_service.block_reply(session, admin, reply, category="OFFENSIVE_LANGUAGE")
    if len(users) > 2:
        await admin_service.suspend_user(session, admin, users[-1], "Publicó reseñas falsas desde varias cuentas.")
    approved = [est for est in establishments if est.status == "APPROVED"]
    if len(approved) > 3:
        await admin_service.suspend_establishment(
            session, admin, approved[-1], "Fotos y menú no corresponden al establecimiento (prueba demo)."
        )
    await session.flush()


async def status() -> None:
    async with session_factory() as session:
        demo_ids = select(User.id).where(User.email.like(f"%@{DEMO_DOMAIN}"))
        n_users = await session.scalar(select(func.count()).select_from(User).where(User.id.in_(demo_ids)))
        n_est = await session.scalar(select(func.count()).select_from(Establishment).where(Establishment.owner_id.in_(demo_ids)))
        n_rev = await session.scalar(select(func.count()).select_from(Review).where(Review.user_id.in_(demo_ids)))
        n_blocked = await session.scalar(
            select(func.count()).select_from(Review).where(Review.user_id.in_(demo_ids), Review.comment_status == "BLOCKED")
        )
        n_reports = await session.scalar(select(func.count()).select_from(Report).where(Report.reporter_id.in_(demo_ids)))
        n_plans = await session.scalar(select(func.count()).select_from(Plan).where(Plan.user_id.in_(demo_ids)))
        n_fav = await session.scalar(select(func.count()).select_from(Favorite).where(Favorite.user_id.in_(demo_ids)))
        n_consents = await session.scalar(select(func.count()).select_from(Consent).where(Consent.user_id.in_(demo_ids)))
    print(
        f"Datos demo: {n_users} usuarios, {n_est} establecimientos, {n_rev} reseñas "
        f"({n_blocked} con el comentario bloqueado), {n_reports} reportes, {n_plans} planes, {n_fav} favoritos, "
        f"{n_consents} consentimientos."
    )


async def teardown() -> None:
    async with session_factory() as session:
        # combo_items.product_id es ON DELETE RESTRICT: si la cascada borra un producto antes que
        # su combo, Postgres falla. Por eso se eliminan primero las composiciones de combos demo.
        demo_est_ids = (
            select(Establishment.id).join(User, Establishment.owner_id == User.id).where(User.email.like(f"%@{DEMO_DOMAIN}"))
        )
        demo_menu_ids = select(MenuItem.id).where(MenuItem.establishment_id.in_(demo_est_ids))
        await session.execute(delete(ComboItem).where(ComboItem.combo_id.in_(demo_menu_ids)))
        # La bitácora no tiene FK al destino: se borran las acciones del admin demo.
        demo_user_ids = select(User.id).where(User.email.like(f"%@{DEMO_DOMAIN}"))
        await session.execute(delete(ModerationAction).where(ModerationAction.admin_id.in_(demo_user_ids)))
        # El resto sí cae por ON DELETE CASCADE.
        result = await session.execute(delete(User).where(User.email.like(f"%@{DEMO_DOMAIN}")))
        await session.commit()
    print(f"Eliminados {result.rowcount} usuarios demo y todo lo asociado.")


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("up", help="Crea los datos demo")
    up.add_argument("--restaurants", type=int, default=len(PLACES))
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
