"""Filtros de logging para minimizar datos personales en los logs."""

import logging

# Rutas cuya query string lleva la ubicación del usuario o el área que mira en el mapa.
LOCATION_QUERY_PATHS = ("/establishments/nearby", "/establishments/map")
REDACTED_QUERY = "[ubicación omitida]"


class RedactLocationQueryFilter(logging.Filter):
    """Quita la query string de `/establishments/nearby` y `/establishments/map` del log de acceso.

    El log de acceso de Uvicorn usa los argumentos (cliente, método, ruta completa, versión HTTP, estado).
    """

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str):
            path, separator, _ = args[2].partition("?")
            if separator and path.rstrip("/").endswith(LOCATION_QUERY_PATHS):
                record.args = (*args[:2], f"{path}?{REDACTED_QUERY}", *args[3:])
        return True


def install_log_filters() -> None:
    """Idempotente: se llama al importar la app y en el lifespan (Uvicorn reconfigura el logging al arrancar)."""
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(existing, RedactLocationQueryFilter) for existing in access_logger.filters):
        access_logger.addFilter(RedactLocationQueryFilter())
