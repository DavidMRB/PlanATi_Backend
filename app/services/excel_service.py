from collections.abc import Iterable, Sequence
from datetime import datetime
from io import BytesIO

from fastapi import Response
from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.time import to_local
from app.models.establishment import Establishment, EstablishmentImage, MenuItem
from app.models.user import User
from app.schemas.review import ReviewPublic
from app.services import restaurant_service, review_service

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLSX_RESPONSE = {200: {"content": {XLSX_MEDIA_TYPE: {"schema": {"type": "string", "format": "binary"}}}}}
DATE_FORMAT = "dd/mm/yyyy hh:mm"
PRICE_FORMAT = '"$"#,##0.00'
ROW_ALIGNMENT = Alignment(vertical="center", wrap_text=True)
HEADER_FONT = Font(name="Arial", size=11, bold=True, color="FFFFFF")
BODY_FONT = Font(name="Arial", size=11, color="17243D")
HEADER_FILL = PatternFill("solid", fgColor="514DDD")
STRIPE_FILL = PatternFill("solid", fgColor="F1F3FF")

# GUIA 5 TEMA: Determinar estado -> traduce el estado almacenado a una etiqueta para Excel.
STATUS_LABELS = {
    "PENDING": "Pendiente",
    "APPROVED": "Aprobado",
    "REJECTED": "Rechazado",
    "SUSPENDED": "Suspendido",
}
TYPE_LABELS = {
    "RESTAURANT": "Restaurante",
    "CAFE": "Café",
    "BAR": "Bar",
    "HOTEL": "Hotel",
    "EXPERIENCE": "Experiencia",
    "STORE": "Tienda",
    "OTHER": "Otro",
}


# GUIA 11 TEMA: Exportación a Excel -> escribe y da formato a cada celda con openpyxl.
def _write_row(sheet: Worksheet, index: int, values: Sequence, *, heading: bool = False) -> None:
    for column, value in enumerate(values, start=1):
        cell = sheet.cell(index, column)
        # GUIA 3 TEMA: if elif else -> distingue texto, fecha y otros valores antes de escribir.
        if isinstance(value, str):
            # El contenido aportado por usuarios se conserva como texto, incluso si empieza con "=".
            cell.value = ILLEGAL_CHARACTERS_RE.sub("", value)
            cell.data_type = "s"
        elif isinstance(value, datetime):
            cell.value = to_local(value).replace(tzinfo=None)
            cell.number_format = DATE_FORMAT
        else:
            cell.value = value
        cell.alignment = ROW_ALIGNMENT
        cell.font = HEADER_FONT if heading else BODY_FONT
        # GUIA 2 TEMA: Aritmética y comparación -> % calcula paridad y == permite alternar filas.
        if heading or index % 2 == 1:
            cell.fill = HEADER_FILL if heading else STRIPE_FILL


# GUIA 11 TEMA: Filas y columnas -> título, encabezados, anchos, filtros y paneles inmovilizados.
def _write_sheet(
    sheet: Worksheet,
    title: str,
    columns: Sequence[tuple[str, int]],
    rows: Iterable[Sequence],
    *,
    formats: dict[int, str] | None = None,
) -> None:
    sheet.sheet_view.showGridLines = False
    sheet.freeze_panes = "A3"
    last_column = get_column_letter(len(columns))
    sheet.merge_cells(f"A1:{last_column}1")
    _write_row(sheet, 1, [title], heading=True)
    sheet["A1"].font = Font(name="Arial", size=15, bold=True, color="FFFFFF")
    sheet.row_dimensions[1].height = 32
    sheet.row_dimensions[2].height = 30
    _write_row(sheet, 2, [name for name, _ in columns], heading=True)
    for column, (_, width) in enumerate(columns, start=1):
        sheet.column_dimensions[get_column_letter(column)].width = width

    last_row = 2
    for last_row, row in enumerate(rows, start=3):
        _write_row(sheet, last_row, row)
        if formats:
            for column, number_format in formats.items():
                sheet.cell(last_row, column).number_format = number_format
    sheet.auto_filter.ref = f"A2:{last_column}{last_row}"


# GUIA 11 TEMA: Generar archivo Excel -> guarda en BytesIO y entrega .xlsx por HTTP sin archivo permanente.
def _download(book: Workbook, filename: str) -> Response:
    book.properties.creator = "PlanATi"
    with BytesIO() as output:
        book.save(output)
        content = output.getvalue()
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "private, no-store"},
    )


# GUIA 11 TEMA: Consultar datos -> obtiene catálogo e imágenes y genera el libro fuera del bucle asíncrono.
async def export_menu(session: AsyncSession, establishment: Establishment) -> Response:
    items = await restaurant_service.list_catalog(session, establishment)
    images = await restaurant_service.list_establishment_images(session, establishment, "MENU")
    return await run_in_threadpool(menu_workbook, establishment.id, establishment.name, items, images)


# GUIA 11 TEMA: Exportar reseñas -> usa la representación pública para respetar la moderación.
async def export_reviews(session: AsyncSession, establishment: Establishment) -> Response:
    reviews, _ = await review_service.list_reviews_for_owner(session, establishment, limit=None)
    public_reviews = [review_service.to_public_review(review) for review in reviews]
    return await run_in_threadpool(reviews_workbook, establishment.id, establishment.name, public_reviews)


def menu_workbook(
    establishment_id: int, name: str, items: list[MenuItem], menu_images: list[EstablishmentImage]
) -> Response:
    # GUIA 11 TEMA: Libro y hojas -> crea Productos, Combos y Composición con openpyxl.
    book = Workbook()
    products = book.active
    products.title = "Productos"
    combos_sheet = book.create_sheet("Combos")
    components = book.create_sheet("Composición")
    columns = [
        ("ID", 10), ("Nombre", 32), ("Descripción", 48), ("Precio (COP)", 17),
        ("Disponible", 15), ("Imagen (URL)", 44),
    ]

    def catalog_row(item: MenuItem) -> tuple:
        return (item.id, item.name, item.description, item.price, "Sí" if item.is_available else "No", item.image_url)

    # GUIA 4 TEMA: Listas -> comprensión que selecciona los combos del catálogo.
    # GUIA 5 TEMA: Clasificar información -> separa productos y combos para sus hojas.
    combos = [item for item in items if item.is_combo]
    _write_sheet(
        products, f"Productos · {name}", columns,
        (catalog_row(item) for item in items if not item.is_combo),
        formats={4: PRICE_FORMAT},
    )
    # GUIA 1 TEMA: Programación funcional -> map transforma cada combo con catalog_row.
    _write_sheet(combos_sheet, f"Combos · {name}", columns, map(catalog_row, combos), formats={4: PRICE_FORMAT})
    _write_sheet(
        components,
        f"Composición de combos · {name}",
        [("ID del combo", 16), ("Combo", 32), ("ID del producto", 20), ("Producto", 32), ("Cantidad", 14)],
        (
            (combo.id, combo.name, part.product_id, part.product_name, part.quantity)
            for combo in combos
            for part in combo.combo_items
        ),
    )
    if menu_images:
        _write_sheet(
            book.create_sheet("Menú físico"),
            f"Menú físico · {name}",
            [("Orden", 12), ("Descripción", 40), ("Imagen (URL)", 72)],
            ((image.display_order, image.caption, image.image_url) for image in menu_images),
        )
    return _download(book, f"menu-establecimiento-{establishment_id}.xlsx")


def reviews_workbook(establishment_id: int, name: str, reviews: list[ReviewPublic]) -> Response:
    book = Workbook()
    sheet = book.active
    sheet.title = "Reseñas"
    columns = [
        ("ID", 10), ("Autor público", 24), ("Puntuación / 5", 16), ("Comentario", 52),
        ("Fecha de reseña (hora local)", 26), ("Estado de respuesta", 23),
        ("Respuesta del establecimiento", 52), ("Última edición de respuesta (hora local)", 31),
    ]
    def review_row(review: ReviewPublic) -> tuple:
        reply = review.reply
        reply_text = None
        if reply:
            reply_text = reply.moderation_notice if reply.comment_blocked else reply.comment
        return (
            review.id, review.author.display_name, review.rating,
            review.moderation_notice if review.comment_blocked else review.comment,
            review.created_at, "Respondida" if reply else "Sin responder",
            reply_text, reply.updated_at if reply else None,
        )

    _write_sheet(sheet, f"Reseñas visibles · {name}", columns, map(review_row, reviews))
    return _download(book, f"resenas-establecimiento-{establishment_id}.xlsx")


# GUIA 11 TEMA: Exportar establecimientos -> genera el directorio administrativo con sus estados y contactos.
def establishments_workbook(establishments: list[tuple[Establishment, User, int]]) -> Response:
    book = Workbook()
    sheet = book.active
    sheet.title = "Establecimientos"
    columns = [
        ("ID", 10), ("Establecimiento", 32), ("Tipo", 18), ("Categoría", 23), ("Estado", 16),
        ("Ciudad", 19), ("Dirección", 36), ("Responsable", 26), ("Teléfono", 19), ("Correo de contacto", 32),
        ("Titular", 26), ("Correo del titular", 32), ("Registro (hora local)", 24), ("Rango de precio", 16),
        ("Puntuación / 5", 16), ("Reseñas", 12), ("Reportes abiertos", 19), ("Latitud", 15), ("Longitud", 15),
        ("Descripción", 52), ("Motivo de rechazo", 40), ("Motivo de suspensión", 40),
    ]
    rows = (
        (
            place.id, place.name, TYPE_LABELS.get(place.establishment_type, place.establishment_type),
            place.category, STATUS_LABELS.get(place.status, place.status), place.city, place.address,
            place.manager_name, place.phone, place.contact_email, owner.full_name, owner.email, place.created_at,
            place.price_range, place.rating_avg, place.rating_count, reports, place.latitude, place.longitude,
            place.description, place.rejection_reason, place.suspension_reason,
        )
        for place, owner, reports in establishments
    )
    _write_sheet(
        sheet, "Directorio administrativo · PlanATi", columns, rows,
        formats={15: "0.00", 18: "0.000000", 19: "0.000000"},
    )
    return _download(book, "establecimientos-planati.xlsx")
