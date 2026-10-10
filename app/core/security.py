from datetime import datetime, timedelta, timezone
import secrets

import jwt
from pwdlib import PasswordHash

from app.core.config import settings

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)


def create_access_token(subject: str) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=60)
    payload = {"sub": subject, "exp": expires_at}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def create_oauth_state() -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
    return jwt.encode({"state": secrets.token_urlsafe(32), "exp": expires_at}, settings.secret_key, algorithm="HS256")


def verify_oauth_state(state: str) -> bool:
    try:
        jwt.decode(state, settings.secret_key, algorithms=["HS256"])
        return True
    except jwt.InvalidTokenError:
        return False
