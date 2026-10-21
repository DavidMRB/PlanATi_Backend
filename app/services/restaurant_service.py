from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.establishment import ComboItem, Establishment, EstablishmentImage, MenuItem
from app.models.user import User


class EstablishmentTransitionError(Exception):
    """Transición de estado incompatible con el estado actual (409)."""


class CatalogValidationError(Exception):
    """Datos de catálogo inválidos, p. ej. productos ajenos o combos anidados (400)."""


class CatalogConflictError(Exception):
    """Operación bloqueada por integridad del catálogo (409)."""


# --- Administración -------------------------------------------------------------------------


async def list_establishments_for_admin(
    session: AsyncSession,
    status_filter: str,
    search: str | None,
    skip: int,
    limit: int,
) -> list[tuple[Establishment, User]]:
    query = select(Establishment, User).join(User, Establishment.owner_id == User.id)
    if status_filter != "ALL":
        query = query.where(Establishment.status == status_filter)
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(
            or_(
                Establishment.name.ilike(pattern),
                Establishment.category.ilike(pattern),
                User.email.ilike(pattern),
            )
        )
    query = query.order_by(Establishment.created_at.desc(), Establishment.id.desc()).offset(skip).limit(limit)
    result = await session.execute(query)
    return [(establishment, owner) for establishment, owner in result.all()]


async def get_establishment_with_owner(
    session: AsyncSession, establishment_id: int
) -> tuple[Establishment, User] | None:
    result = await session.execute(
        select(Establishment, User)
        .join(User, Establishment.owner_id == User.id)
        .where(Establishment.id == establishment_id)
    )
    row = result.first()
    return (row[0], row[1]) if row is not None else None


async def approve_establishment(session: AsyncSession, establishment: Establishment) -> Establishment:
    if establishment.status == "APPROVED":
        raise EstablishmentTransitionError("El establecimiento ya se encuentra aprobado")
    if establishment.status != "PENDING":
        raise EstablishmentTransitionError(
            "Solo se pueden aprobar solicitudes en estado PENDING; el restaurante debe re-aplicar"
        )
    establishment.status = "APPROVED"
    establishment.rejection_reason = None
    await session.commit()
    await session.refresh(establishment)
    return establishment


async def reject_establishment(
    session: AsyncSession, establishment: Establishment, reason: str
) -> Establishment:
    if establishment.status == "REJECTED":
        raise EstablishmentTransitionError("El establecimiento ya está rechazado")
    # PENDING -> REJECTED (rechazo) y APPROVED -> REJECTED (suspensión administrativa).
    establishment.status = "REJECTED"
    establishment.rejection_reason = reason.strip()
    await session.commit()
    await session.refresh(establishment)
    return establishment


# --- Perfil y re-aplicación -----------------------------------------------------------------


async def update_establishment_profile(
    session: AsyncSession, establishment: Establishment, changes: dict[str, Any]
) -> Establishment:
    for field, value in changes.items():
        setattr(establishment, field, value)
    await session.commit()
    await session.refresh(establishment)
    return establishment


async def reapply_establishment(
    session: AsyncSession, establishment: Establishment, changes: dict[str, Any]
) -> Establishment:
    if establishment.status != "REJECTED":
        raise EstablishmentTransitionError("Solo un establecimiento rechazado puede volver a postularse")
    for field, value in changes.items():
        setattr(establishment, field, value)
    establishment.status = "PENDING"
    establishment.rejection_reason = None
    await session.commit()
    await session.refresh(establishment)
    return establishment


# --- Imágenes -------------------------------------------------------------------------------


async def list_establishment_images(
    session: AsyncSession, establishment: Establishment, image_type: str | None
) -> list[EstablishmentImage]:
    query = select(EstablishmentImage).where(EstablishmentImage.establishment_id == establishment.id)
    if image_type:
        query = query.where(EstablishmentImage.image_type == image_type)
    result = await session.scalars(query.order_by(EstablishmentImage.display_order, EstablishmentImage.id))
    return list(result.all())


async def add_establishment_image(
    session: AsyncSession, establishment: Establishment, data: dict[str, Any]
) -> EstablishmentImage:
    image = EstablishmentImage(establishment_id=establishment.id, **data)
    session.add(image)
    await session.commit()
    await session.refresh(image)
    return image


async def delete_establishment_image(
    session: AsyncSession, establishment: Establishment, image_id: int
) -> bool:
    image = await session.scalar(
        select(EstablishmentImage).where(
            EstablishmentImage.id == image_id,
            EstablishmentImage.establishment_id == establishment.id,
        )
    )
    if image is None:
        return False
    await session.delete(image)
    await session.commit()
    return True


# --- Catálogo: productos y combos -----------------------------------------------------------


def _catalog_query(establishment: Establishment):
    return (
        select(MenuItem)
        .where(MenuItem.establishment_id == establishment.id)
        .options(selectinload(MenuItem.combo_items).joinedload(ComboItem.product))
        .execution_options(populate_existing=True)
    )


async def list_catalog(session: AsyncSession, establishment: Establishment) -> list[MenuItem]:
    result = await session.scalars(_catalog_query(establishment).order_by(MenuItem.is_combo, MenuItem.id))
    return list(result.unique().all())


async def get_catalog_item(
    session: AsyncSession, establishment: Establishment, item_id: int, *, is_combo: bool
) -> MenuItem | None:
    # Filtrar por establecimiento evita IDOR: un ítem ajeno se comporta como inexistente.
    return await session.scalar(
        _catalog_query(establishment).where(MenuItem.id == item_id, MenuItem.is_combo.is_(is_combo))
    )


async def _reload_item(session: AsyncSession, establishment: Establishment, item_id: int) -> MenuItem:
    item = await session.scalar(_catalog_query(establishment).where(MenuItem.id == item_id))
    assert item is not None
    return item


async def create_product(
    session: AsyncSession, establishment: Establishment, data: dict[str, Any]
) -> MenuItem:
    product = MenuItem(establishment_id=establishment.id, is_combo=False, **data)
    session.add(product)
    await session.commit()
    return await _reload_item(session, establishment, product.id)


async def update_catalog_item(
    session: AsyncSession, establishment: Establishment, item: MenuItem, changes: dict[str, Any]
) -> MenuItem:
    for field, value in changes.items():
        setattr(item, field, value)
    await session.commit()
    return await _reload_item(session, establishment, item.id)


async def delete_product(session: AsyncSession, product: MenuItem) -> None:
    result = await session.scalars(
        select(MenuItem.name)
        .join(ComboItem, ComboItem.combo_id == MenuItem.id)
        .where(ComboItem.product_id == product.id)
        .order_by(MenuItem.name)
    )
    combo_names = list(dict.fromkeys(result.all()))
    if combo_names:
        raise CatalogConflictError(
            "El producto forma parte de los combos: " + ", ".join(combo_names)
            + ". Retíralo de esos combos antes de eliminarlo."
        )
    await session.delete(product)
    await session.commit()


async def _build_combo_items(
    session: AsyncSession,
    establishment: Establishment,
    items: list[dict[str, int]],
    combo_id: int | None = None,
) -> list[ComboItem]:
    quantities: dict[int, int] = {}
    for item in items:
        quantities[item["product_id"]] = quantities.get(item["product_id"], 0) + item["quantity"]
    if not quantities:
        return []
    if combo_id is not None and combo_id in quantities:
        raise CatalogValidationError("Un combo no puede incluirse a sí mismo")

    result = await session.scalars(
        select(MenuItem).where(
            MenuItem.id.in_(quantities),
            MenuItem.establishment_id == establishment.id,
        )
    )
    products = {product.id: product for product in result.all()}
    missing = sorted(set(quantities) - set(products))
    if missing:
        raise CatalogValidationError(
            f"Los productos {missing} no existen o no pertenecen a tu establecimiento"
        )
    nested = sorted(product.name for product in products.values() if product.is_combo)
    if nested:
        raise CatalogValidationError(f"Un combo no puede contener otros combos: {', '.join(nested)}")
    return [ComboItem(product_id=product_id, quantity=quantity) for product_id, quantity in quantities.items()]


async def create_combo(
    session: AsyncSession, establishment: Establishment, data: dict[str, Any]
) -> MenuItem:
    items = data.pop("items")
    combo_items = await _build_combo_items(session, establishment, items)
    combo = MenuItem(establishment_id=establishment.id, is_combo=True, **data)
    combo.combo_items = combo_items
    session.add(combo)
    await session.commit()
    return await _reload_item(session, establishment, combo.id)


async def update_combo(
    session: AsyncSession, establishment: Establishment, combo: MenuItem, changes: dict[str, Any]
) -> MenuItem:
    items = changes.pop("items", None)
    if items is not None:
        # delete-orphan elimina la composición anterior al reemplazar la colección.
        combo.combo_items = await _build_combo_items(session, establishment, items, combo_id=combo.id)
    for field, value in changes.items():
        setattr(combo, field, value)
    await session.commit()
    return await _reload_item(session, establishment, combo.id)


async def delete_combo(session: AsyncSession, combo: MenuItem) -> None:
    await session.delete(combo)
    await session.commit()
