from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LegalVersionsResponse(BaseModel):
    privacy_policy: str
    terms: str


class ConsentAcceptance(BaseModel):
    """Campos de aceptación que exigen los registros (`POST /auth/register` y `/auth/restaurant/register`).

    No hay edad mínima (decisión D10): el titular solo declara aceptar la política de tratamiento de
    datos y los términos. `Literal[True]` hace que una casilla sin marcar o ausente dé 422.
    """

    accept_privacy_policy: Literal[True]
    accept_terms: Literal[True]
    privacy_policy_version: str = Field(min_length=1, max_length=20)
    terms_version: str = Field(min_length=1, max_length=20)


class ConsentAcceptRequest(BaseModel):
    privacy_policy_version: str = Field(min_length=1, max_length=20)
    terms_version: str = Field(min_length=1, max_length=20)


class ConsentItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document: Literal["PRIVACY_POLICY", "TERMS"]
    version: str
    channel: str
    accepted_at: datetime


class DeleteAccountRequest(BaseModel):
    """Confirmación de `DELETE /users/me`: la palabra ELIMINAR y la contraseña **o** el código SMS."""

    confirmation: Literal["ELIMINAR"]
    password: str | None = Field(default=None, min_length=1, max_length=128)
    code: str | None = Field(default=None, pattern=r"^\d{6}$")

    @model_validator(mode="after")
    def _one_proof(self) -> "DeleteAccountRequest":
        if (self.password is None) == (self.code is None):
            raise ValueError("Envía la contraseña o el código SMS (solo uno de los dos).")
        return self
