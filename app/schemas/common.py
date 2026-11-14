from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Respuesta paginada común para los endpoints nuevos."""

    items: list[T]
    total: int
    skip: int
    limit: int
