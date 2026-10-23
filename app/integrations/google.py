from urllib.parse import urlencode

import httpx
from google.auth.transport import requests
from google.auth.exceptions import GoogleAuthError
from google.oauth2 import id_token

from app.core.config import settings


class GoogleOAuthError(ValueError):
    pass


class GoogleOAuthClient:
    authorization_endpoint = "https://accounts.google.com/o/oauth2/v2/auth"
    token_endpoint = "https://oauth2.googleapis.com/token"

    def authorization_url(self, state: str) -> str:
        if not settings.google_client_id:
            raise GoogleOAuthError("Google OAuth no está configurado")
        params = {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": "openid email profile",
            "state": state,
            "access_type": "offline",
            "prompt": "select_account",
        }
        return f"{self.authorization_endpoint}?{urlencode(params)}"

    async def authenticate_code(self, code: str) -> dict[str, str | bool | None]:
        if not settings.google_client_id or not settings.google_client_secret:
            raise GoogleOAuthError("Google OAuth no está configurado")
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(
                self.token_endpoint,
                data={
                    "code": code,
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret,
                    "redirect_uri": settings.google_redirect_uri,
                    "grant_type": "authorization_code",
                },
            )
        if response.is_error:
            raise GoogleOAuthError("No se pudo validar el código de Google")
        token_data = response.json()
        try:
            claims = id_token.verify_oauth2_token(
                token_data["id_token"], requests.Request(), settings.google_client_id
            )
            return {
                "google_sub": str(claims["sub"]),
                "email": claims.get("email"),
                "name": claims.get("name"),
                "picture": claims.get("picture"),
                "email_verified": claims.get("email_verified"),
            }
        except (KeyError, ValueError, GoogleAuthError) as error:
            raise GoogleOAuthError("La identidad de Google no es válida") from error
