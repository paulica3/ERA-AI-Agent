"""Database engine, session, and base for the adaptive learning system.

Production uses PostgreSQL via DATABASE_URL (Railway managed). Local dev falls
back to a SQLite file under the data dir. SQLite needs check_same_thread=False
so FastAPI's threadpool can share the connection.
"""

from __future__ import annotations

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from era_agent.config import DATABASE_URL, DATA_DIR

# Ensure the data dir exists when using the SQLite fallback.
if DATABASE_URL.startswith("sqlite"):
    os.makedirs(DATA_DIR, exist_ok=True)
    connect_args = {"check_same_thread": False}
else:
    connect_args = {}

engine = create_engine(DATABASE_URL, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def get_db():
    """FastAPI dependency yielding a session that is always closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create tables for dev / first boot. Production uses Alembic migrations,
    but create_all is idempotent and safe to call on startup as a fallback."""
    from era_agent.db import models  # noqa: F401  (register models on Base)
    Base.metadata.create_all(bind=engine)
