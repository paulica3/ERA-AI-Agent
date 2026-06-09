"""Password hashing and JWT issue/verify.

Uses pbkdf2_sha256 (pure-Python, no native dependency) so it runs identically
on the dev machine and the Railway container. JWTs are signed with JWT_SECRET.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from era_agent.config import JWT_SECRET, JWT_EXPIRY_MINUTES

_pwd = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
_ALGO = "HS256"


def hash_password(password: str) -> str:
    return _pwd.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _pwd.verify(password, password_hash)
    except ValueError:
        return False


def create_access_token(user_id: int) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + timedelta(minutes=JWT_EXPIRY_MINUTES),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=_ALGO)


def decode_token(token: str) -> int | None:
    """Return the user id from a valid token, or None if invalid/expired."""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[_ALGO])
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
