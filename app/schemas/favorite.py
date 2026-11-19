from pydantic import BaseModel


class FavoriteIdsResponse(BaseModel):
    """Ids de los establecimientos favoritos (aprobados) del usuario, el más reciente primero."""

    establishment_ids: list[int]
