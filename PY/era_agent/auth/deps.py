"""FastAPI dependency that resolves the authenticated user from the Bearer JWT.

user_id always comes from the verified token, never from request input.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from era_agent.auth.security import decode_token
from era_agent.db.database import get_db
from era_agent.db.models import User


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Autentificare necesară.")
    token = authorization.split(" ", 1)[1].strip()
    user_id = decode_token(token)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Sesiune invalidă sau expirată.")
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Utilizatorul nu există.")
    return user
